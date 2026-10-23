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

# The desktop entry points are shipped without a .sh extension.
for script in packages/bme-config/root/usr/bin/bluemess-desktop packages/bme-config/root/usr/lib/blue-mess/desktop-session packages/bme-config/root/etc/profile.d/blue-mess-desktop.sh packages/bme-config/root/usr/share/blue-mess/skel/.xinitrc; do
    busybox ash -n "$script"
done
python3 - <<'XML'
from pathlib import Path
import xml.etree.ElementTree as ET
for path in Path('packages/bme-config/root/usr/share/blue-mess/skel/.config').rglob('*.xml'):
    ET.parse(path)
XML
