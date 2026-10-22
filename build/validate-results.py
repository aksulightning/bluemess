"""Fail closed before assigning the validated artifact name."""
import json
import pathlib
import sys
out = pathlib.Path(sys.argv[1])
verification = json.loads((out / 'verification/results.json').read_text())
if verification.get('status') != 'passed':
    raise SystemExit('VM verification is incomplete or failed')
memory = json.loads((out / 'verification/memory.json').read_text())
readings = memory['readings']
if len(readings) != 3 or any((r['MemTotal_kib'] - r['MemAvailable_kib']) / 1024 > 150 or r['SwapUsed_kib'] != 0 for r in readings):
    raise SystemExit('Three-boot memory acceptance failed')
metadata = json.loads((out / 'build-metadata.json').read_text())
metadata['validated'] = True
(out / 'build-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
