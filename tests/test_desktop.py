"""User preference and tty guards; no X server or real login is started."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

COMMAND = Path(__file__).resolve().parents[1] / 'packages/bme-config/root/usr/bin/bluemess-desktop'
SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))


class DesktopCommand(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        for name, body in {
            'id': 'echo "${TEST_UID:-1000}"',
            'tty': 'echo "${TEST_TTY:-/dev/tty1}"',
            'startx': 'echo desktop-started',
        }.items():
            p = self.bin / name
            p.write_text('#!/bin/sh\n' + body + '\n')
            p.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'),
                        PATH=str(self.bin) + ':' + os.environ['PATH'], DISPLAY='', WAYLAND_DISPLAY='')

    def run_command(self, *args, **env):
        return subprocess.run(SHELL + [str(COMMAND), *args], env=dict(self.env, **env),
                              text=True, capture_output=True, timeout=10)

    def test_preference_roundtrip_and_invalid_input(self):
        self.assertIn('false', self.run_command('status').stdout)
        for value in ('true', 'false'):
            self.assertEqual(self.run_command('auto-start', value).returncode, 0)
            self.assertIn(value, self.run_command('status').stdout)
        self.run_command('auto-start', 'true')
        self.assertEqual((self.home / '.profile').read_text().count('# Blue Mess desktop login hook'), 1)
        self.run_command('auto-start', 'false')
        self.assertNotEqual(self.run_command('auto-start', 'yes').returncode, 0)
        self.assertIn('false', self.run_command('status').stdout)
        self.assertNotEqual(self.run_command('auto-start', 'true', TEST_UID='0').returncode, 0)

    def test_login_starts_only_enabled_ordinary_user_on_tty1(self):
        self.assertNotIn('desktop-started', self.run_command('--login').stdout)
        self.run_command('auto-start', 'true')
        self.assertIn('desktop-started', self.run_command('--login').stdout)
        for env in ({'TEST_UID': '0'}, {'TEST_TTY': '/dev/tty2'}, {'TEST_TTY': '/dev/ttyS0'},
                    {'TEST_TTY': '/dev/pts/0'}, {'DISPLAY': ':0'}, {'WAYLAND_DISPLAY': 'wayland-0'}):
            with self.subTest(env=env):
                self.assertNotIn('desktop-started', self.run_command('--login', **env).stdout)

    def test_manual_start_obeys_same_tty_and_user_guards(self):
        self.assertIn('desktop-started', self.run_command('start').stdout)
        for env in ({'TEST_TTY': '/dev/tty2'}, {'TEST_UID': '0'}, {'DISPLAY': ':0'}):
            self.assertNotEqual(self.run_command('start', **env).returncode, 0)
