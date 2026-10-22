"""Fail closed before assigning the validated artifact name."""
import hashlib
import json
import pathlib
import sys
out = pathlib.Path(sys.argv[1])
for name in ('SHA256SUMS', 'target-packages.tsv', 'installer-packages.tsv',
             'build-tools.tsv', 'build-metadata.json', 'build-metadata.txt',
             'builder-image.json', 'repositories.list', 'logs/build.log',
             'logs/iso-layout.log', 'verification/report.md',
             'verification/installer-engine.log', 'verification/memory.json'):
    if not (out / name).is_file() or (out / name).stat().st_size == 0:
        raise SystemExit(f'Required artifact missing or empty: {name}')
verification = json.loads((out / 'verification/results.json').read_text())
if verification.get('status') != 'passed':
    raise SystemExit('VM verification is incomplete or failed')
iso = out / verification['iso']
with iso.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
if digest != verification['iso_sha256']:
    raise SystemExit('Verification report belongs to different ISO bytes')
memory = json.loads((out / 'verification/memory.json').read_text())
readings = memory['readings']
if len(readings) != 3 or any((r['MemTotal_kib'] - r['MemAvailable_kib']) / 1024 > 150 or r['SwapUsed_kib'] != 0 for r in readings):
    raise SystemExit('Three-boot memory acceptance failed')
metadata = json.loads((out / 'build-metadata.json').read_text())
metadata['validated'] = True
(out / 'build-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
