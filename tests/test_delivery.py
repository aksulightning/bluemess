"""Publication gate tests use synthetic bytes, never represent a real ISO run."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'build/validate-results.py'


class DeliveryGate(unittest.TestCase):
    def prepare(self, root):
        for name in ('SHA256SUMS', 'target-packages.tsv', 'installer-packages.tsv',
                     'build-tools.tsv', 'build-metadata.txt', 'builder-image.json',
                     'repositories.list', 'logs/build.log', 'logs/iso-layout.log',
                     'verification/report.md', 'verification/installer-engine.log'):
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('test fixture\n')
        (root / 'fixture.iso').write_bytes(b'synthetic fixture, not an ISO')
        (root / 'build-metadata.json').write_text('{"validated": false}')
        (root / 'verification/results.json').write_text(json.dumps({
            'status': 'passed', 'iso': 'fixture.iso',
            'iso_sha256': hashlib.sha256((root / 'fixture.iso').read_bytes()).hexdigest()}))
        readings = [{'MemTotal_kib': 1024000, 'MemAvailable_kib': 870400,
                     'SwapUsed_kib': 0} for _ in range(3)]
        (root / 'verification/memory.json').write_text(json.dumps({'readings': readings}))

    def run_gate(self, root):
        return subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)

    def test_matching_complete_results_accept_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            result = self.run_gate(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads((root / 'build-metadata.json').read_text())['validated'])

    def test_changed_bytes_cannot_reuse_a_passed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            (root / 'fixture.iso').write_bytes(b'different candidate')
            result = self.run_gate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('different ISO bytes', result.stderr)

    def test_missing_manifest_cannot_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            (root / 'target-packages.tsv').unlink()
            self.assertNotEqual(self.run_gate(root).returncode, 0)

    def test_partial_or_over_budget_measurements_cannot_publish(self):
        for readings in ([], [{'MemTotal_kib': 1024000, 'MemAvailable_kib': 870399,
                              'SwapUsed_kib': 0}] * 3):
            with self.subTest(readings=readings), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.prepare(root)
                (root / 'verification/memory.json').write_text(json.dumps({'readings': readings}))
                self.assertNotEqual(self.run_gate(root).returncode, 0)
