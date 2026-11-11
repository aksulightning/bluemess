"""Exercise user setup and mutually exclusive network ownership without root."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'packages/bme-config/root'
SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))


class Additions(unittest.TestCase):
    def test_flatpak_setup_is_per_user_and_propagates_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name, body in {
                'id': 'echo "${TEST_UID:-1207}"',
                'flatpak': 'echo "$*" >> "$TRACE"; exit "${TEST_FAILURE:-0}"',
            }.items():
                file = base / name
                file.write_text('#!/bin/sh\n' + body + '\n')
                file.chmod(0o755)
            env = dict(os.environ, PATH=tmp + ':' + os.environ['PATH'], TRACE=tmp + '/trace')
            script = str(PAYLOAD / 'usr/bin/bluemess-install-flatpaks')
            result = subprocess.run(SHELL + [script], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = (base / 'trace').read_text().splitlines()
            self.assertEqual(len(commands), 2)
            self.assertTrue(all('--user' in line for line in commands))
            self.assertIn('com.valvesoftware.Steam', commands[1])
            (base / 'trace').unlink()
            result = subprocess.run(SHELL + [script], env=dict(env, TEST_UID='0'), capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((base / 'trace').exists())
            result = subprocess.run(SHELL + [script], env=dict(env, TEST_FAILURE='7'), capture_output=True)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(len((base / 'trace').read_text().splitlines()), 1)

    def test_network_owners_reject_running_or_enabled_competitor(self):
        for owner, other in [('network-manager', 'bme-network'), ('bme-network', 'network-manager')]:
            for running, enabled in [(False, False), (True, False), (False, True)]:
                with self.subTest(owner=owner, running=running, enabled=enabled), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    levels = root / 'runlevels/default'
                    levels.mkdir(parents=True)
                    if enabled:
                        (levels / other).symlink_to('/etc/init.d/' + other)
                    source = (PAYLOAD / 'usr/share/blue-mess/init.d' / owner).read_text()
                    source = source.replace('/etc/runlevels', str(root / 'runlevels'))
                    script = root / 'service'
                    script.write_text(source)
                    stub = root / 'rc-service'
                    stub.write_text('#!/bin/sh\nexit "$RUNNING"\n')
                    stub.chmod(0o755)
                    command = 'eerror() { echo "$*"; }; . "$1"; start_pre'
                    result = subprocess.run(SHELL + ['-c', command, 'test', str(script)],
                                            env=dict(os.environ, PATH=tmp + ':' + os.environ['PATH'], RUNNING='0' if running else '1'),
                                            capture_output=True)
                    self.assertEqual(result.returncode == 0, not (running or enabled))
