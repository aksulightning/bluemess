#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'CHECK'
import pathlib, subprocess
for directory in ('build', 'packages', 'config'):
    for script in pathlib.Path(directory).rglob('*.sh'):
        subprocess.run(['bash', '-n', str(script)], check=True)
CHECK
busybox ash -n installer/bme-install
busybox ash -n installer/lib/install.sh
BME_TEST_SHELL='busybox ash' python3 -m unittest discover -s tests -v
# POSIX shell dialect checks, with only sourced-file discovery disabled.
shellcheck -s ash -e SC1091 installer/bme-install installer/lib/install.sh
