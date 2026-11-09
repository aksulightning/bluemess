"""Build-root console layout and boot command-line behavior; no host changes."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))


class ConsoleLayout(unittest.TestCase):
    def test_target_and_installer_have_only_three_virtual_login_consoles(self):
        for role in ('target', 'installer'):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = base / 'root'
                for folder in ('etc/init.d', 'etc/UPower', 'usr/share/blue-mess'):
                    (root / folder).mkdir(parents=True)
                (root / 'etc/UPower/UPower.conf').write_text('CriticalPowerAction=HybridSleep\n')
                (root / 'usr/share/blue-mess/os-release').write_text('ID=bluemess\n')
                (root / 'etc/init.d/greetd').touch()
                (root / 'etc/init.d/greetd').chmod(0o755)
                binary = base / 'bin'
                binary.mkdir()
                # All runtime interpreter checks belong to the real image build.
                stub = binary / 'chroot'
                stub.write_text('#!/bin/sh\nexit 0\n')
                stub.chmod(0o755)
                result = subprocess.run(SHELL + [str(ROOT / 'config/configure-root.sh'), str(root), role],
                                        env=dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH']),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                links = {p.name for p in (root / 'etc/runlevels/default').iterdir()}
                expected = {'bme-getty.tty2', 'bme-getty.tty3', 'bme-getty.ttyS0'}
                if role == 'installer':
                    expected.add('bme-getty.tty1')
                    self.assertIn('bme-console', links)
                    self.assertNotIn('greetd', links)
                else:
                    self.assertIn('greetd', links)
                self.assertEqual({p for p in links if p.startswith('bme-getty.')}, expected)
                self.assertFalse((root / 'etc/init.d/bme-getty.tty4').exists())

    def test_grub_routes_console_to_tty4_and_preserves_other_arguments(self):
        config = ROOT / 'packages/bme-config/root/etc/default/grub.d/90-blue-mess.cfg'
        command = '''
GRUB_CMDLINE_LINUX='root=UUID=test console=tty0 console=ttyS0,9600 quiet'
GRUB_CMDLINE_LINUX_DEFAULT='quiet splash console=tty1'
. "$1"
printf '%s\\n' "$GRUB_CMDLINE_LINUX" "$GRUB_CMDLINE_LINUX_DEFAULT"
'''
        result = subprocess.run(SHELL + ['-c', command, 'test', str(config)],
                                capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0].split(), ['root=UUID=test', 'console=ttyS0,115200n8', 'console=tty4'])
        self.assertEqual(lines[1].split(), ['splash'])

    def test_getty_refuses_diagnostics_and_other_virtual_consoles(self):
        script = ROOT / 'packages/bme-config/root/usr/share/blue-mess/init.d/bme-getty'
        for tty in ('tty4', 'tty5', 'tty6', 'tty12'):
            result = subprocess.run(SHELL + ['-c', 'eerror() { echo "$*"; }; . "$1"; start_pre',
                                            'test', str(script)],
                                    env=dict(os.environ, RC_SVCNAME='bme-getty.' + tty),
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Login is disabled', result.stdout)

