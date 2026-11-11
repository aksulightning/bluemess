"""Retain Debian's packaging and change only the binary identity and version."""
from pathlib import Path
import sys
import re

version = sys.argv[1]
control = Path('debian/control')
text = control.read_text()
text, count = re.subn(r'^Maintainer: (.+)$',
    r'Maintainer: Blue Mess Edition contributors <bluemess@users.noreply.github.com>\nXSBC-Original-Maintainer: \1',
    text, flags=re.MULTILINE)
assert count == 1
assert text.count('Package: tuigreet\n') == 1
text = text.replace('Package: tuigreet\n', f'''Package: tuigreet-bme
Built-Using: ${{cargo:Built-Using}}
Static-Built-Using: ${{cargo:Static-Built-Using}}
Provides: tuigreet (= {version})
Conflicts: tuigreet
Replaces: tuigreet
''')
# The original package did not declare greetd, although its tmpfiles needs _greetd.
text = text.replace('Depends:\n ${misc:Depends}', 'Depends:\n greetd,\n ${misc:Depends}')
control.write_text(text)
for path in Path('debian').glob('tuigreet.*'):
    path.rename(path.with_name(path.name.replace('tuigreet.', 'tuigreet-bme.', 1)))
changelog = Path('debian/changelog')
changelog.write_text(f'''tuigreet ({version}) unstable; urgency=medium

  * Build tuigreet-bme with a backport of upstream 3e18bcb7b68dfe5b8491ad08d5fbcbb326849a4f.
    Start terminal events only after terminal initialization (Debian #1153617).
  * Avoid querying the cursor again while clearing the screen at exit.
  * Provide and replace tuigreet, retaining its command, manual and cache paths.

 -- Blue Mess Edition contributors <bluemess@users.noreply.github.com>  Wed, 11 Nov 2026 12:00:00 +0000

''' + changelog.read_text())
