"""Exercise next-boot selection on an isolated root, without host service changes."""
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'packages/bme-config/root'
SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))


class Switcher(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.trace = self.root / 'trace'
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        TRACE=str(self.trace), FIXTURE=str(self.root))
        for directory in ('etc/init.d', 'etc/runlevels/default', 'etc/runlevels/boot',
                          'etc/blue-mess', 'etc/X11', 'etc/greetd', 'run/lock', 'sbin'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.install('usr/lib/blue-mess/greeter-common')
        self.script = self.install('usr/bin/bluemess-greeter-switcher')
        for name in ('greetd', 'sddm', 'bme-getty.tty1'):
            self.executable('etc/init.d/' + name)
        for name in ('usr/sbin/greetd', 'usr/bin/tuigreet', 'sbin/agetty'):
            self.executable(name)
        self.executable('usr/lib/blue-mess/sddm-check', 'exit "${SDDM_CHECK:-0}"')
        (self.root / 'etc/greetd/blue-mess.toml').touch()
        self.stub('id', 'echo "${FAKE_UID:-0}"')
        self.stub('getent', 'exit 0')
        self.stub('rc-service', 'echo "$*" >> "$TRACE"; [ "$1" = "${RUNNING:-}" ]')
        self.stub('mv', '''
case "$*" in
    *etc/blue-mess/greeter)
        if [ "${FAIL_COMMIT:-0}" = 1 ]; then exit 1; fi ;;
esac
exec /bin/mv "$@"
''')
        for name in ('greetd', 'bme-getty.tty2', 'bme-getty.tty3', 'bme-getty.ttyS0'):
            (self.root / 'etc/runlevels/default' / name).symlink_to(str(self.root / 'etc/init.d' / name))

    def rewrite(self, text):
        return re.sub(r'/(?:etc|usr|sbin|run)/', lambda match: str(self.root) + match[0], text)

    def install(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.rewrite((PAYLOAD / name).read_text()))
        path.chmod(0o755)
        return path

    def executable(self, name, body='exit 0'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def stub(self, name, body):
        self.executable('bin/' + name, body)

    def run_command(self, *args, input=None, **env):
        return subprocess.run(SHELL + [str(self.script), *args],
                              env=dict(self.env, **env), input=input,
                              capture_output=True, text=True, timeout=5)

    def selected(self, choice):
        service = {'tuigreet': 'greetd', 'agetty': 'bme-getty.tty1', 'sddm': 'sddm'}[choice]
        self.assertEqual((self.root / 'etc/blue-mess/greeter').read_text(), choice + '\n')
        self.assertEqual({p.name for p in (self.root / 'etc/runlevels/default').iterdir()},
                         {service, 'bme-getty.tty2', 'bme-getty.tty3', 'bme-getty.ttyS0'})

    def test_roundtrip_idempotence_and_upgrade_preserves_selection(self):
        for choice in ('sddm', 'agetty', 'tuigreet', 'sddm'):
            for action in (choice, choice, '--sync'):
                with self.subTest(action=action, choice=choice):
                    result = self.run_command(action)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.selected(choice)
        self.assertFalse(self.trace.exists(), 'Selection must not stop/start/restart services')

    def test_status_distinguishes_running_service_from_next_boot(self):
        self.assertEqual(self.run_command('sddm').returncode, 0)
        status = self.run_command('status', RUNNING='greetd', FAKE_UID='1000')
        self.assertEqual(status.returncode, 0)
        self.assertIn('Next boot: sddm', status.stdout)
        self.assertIn('Running: greetd', status.stdout)
        self.assertEqual(self.trace.read_text().splitlines(),
                         ['greetd status', 'bme-getty.tty1 status', 'sddm status'])

    def test_menu_and_invalid_or_unprivileged_requests(self):
        self.assertEqual(self.run_command(input='2\n').returncode, 0)
        self.selected('agetty')
        for args, env in ((('bogus',), {}), (('sddm', 'extra'), {}),
                          (('sddm',), {'FAKE_UID': '1000'})):
            self.assertNotEqual(self.run_command(*args, **env).returncode, 0)
            self.selected('agetty')

    def test_prerequisite_and_lock_failures_preserve_previous_choice(self):
        self.assertEqual(self.run_command('tuigreet').returncode, 0)
        self.assertNotEqual(self.run_command('sddm', SDDM_CHECK='1').returncode, 0)
        self.selected('tuigreet')
        (self.root / 'run/lock/bluemess-greeter-switcher.lock').mkdir()
        self.assertNotEqual(self.run_command('sddm').returncode, 0)
        self.selected('tuigreet')

    def test_failed_commit_rolls_back_links_and_both_state_files(self):
        self.assertEqual(self.run_command('agetty').returncode, 0)
        manager = (self.root / 'etc/X11/default-display-manager').read_text()
        result = self.run_command('sddm', FAIL_COMMIT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('restoring the previous', result.stderr)
        self.selected('agetty')
        self.assertEqual((self.root / 'etc/X11/default-display-manager').read_text(), manager)
        self.assertFalse((self.root / 'run/lock/bluemess-greeter-switcher.lock').exists())

    def test_removes_old_managed_links_from_other_runlevels(self):
        (self.root / 'etc/runlevels/boot/greetd').symlink_to(str(self.root / 'etc/init.d/greetd'))
        self.assertEqual(self.run_command('sddm').returncode, 0)
        self.assertFalse((self.root / 'etc/runlevels/boot/greetd').is_symlink())
        self.selected('sddm')

    def test_live_installer_and_unmanaged_links_are_rejected(self):
        link = self.root / 'etc/runlevels/default/bme-media'
        link.symlink_to('/nonexistent')
        self.assertNotEqual(self.run_command('sddm').returncode, 0)
        link.unlink()
        (self.root / 'etc/runlevels/boot/sddm').write_text('custom service')
        self.assertNotEqual(self.run_command('sddm').returncode, 0)
        self.assertTrue((self.root / 'etc/runlevels/default/greetd').is_symlink())

    def test_invalid_saved_state_is_not_executed_or_silently_defaulted(self):
        (self.root / 'etc/blue-mess/greeter').write_text('$(touch ' + str(self.root / 'BAD') + ')')
        for action in ('status', '--sync'):
            self.assertNotEqual(self.run_command(action).returncode, 0)
        self.assertFalse((self.root / 'BAD').exists())
        self.assertEqual(self.run_command('tuigreet').returncode, 0)

    def test_service_guard_rejects_running_or_enabled_competitor(self):
        common = self.root / 'usr/lib/blue-mess/greeter-common'
        for choice in ('tuigreet', 'agetty', 'sddm'):
            self.assertEqual(self.run_command(choice).returncode, 0)
            script = '. "$1"; greeter_start_allowed "$2"'
            for requested in ('tuigreet', 'agetty', 'sddm'):
                result = subprocess.run(SHELL + ['-c', script, 'test', str(common), requested],
                                        env=self.env, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, choice == requested)
            competitor = 'greetd' if choice != 'tuigreet' else 'sddm'
            result = subprocess.run(SHELL + ['-c', script, 'test', str(common), choice],
                                    env=dict(self.env, RUNNING=competitor), capture_output=True)
            self.assertNotEqual(result.returncode, 0)


class SddmSessionCheck(unittest.TestCase):
    def test_accepts_sddm_assigned_vt_but_rejects_wrong_seat_remote_or_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            script = root / 'loginctl'
            script.write_text('''#!/bin/sh
if [ "$1" = show-user ]; then echo "$XDG_RUNTIME_DIR"; else
printf 'User=%s\nSeat=%s\nTTY=%s\nActive=yes\nRemote=%s\nService=%s\nType=%s\nVTNr=%s\n' \
    "$(id -u)" "${SEAT:-seat0}" "${TTY:-tty7}" "${REMOTE:-no}" \
    "${SERVICE:-sddm}" "${TYPE:-x11}" "${VT:-7}"
fi
''')
            script.chmod(0o755)
            # The builder runs as root; model an ordinary session consistently.
            for name, body in {
                'id': 'echo 1000',
                'stat': 'if [ "$2" = "%u:%a" ]; then echo 1000:700; else exec /usr/bin/stat "$@"; fi',
            }.items():
                stub = root / name
                stub.write_text('#!/bin/sh\n' + body + '\n')
                stub.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       XDG_RUNTIME_DIR=str(runtime), DISPLAY='')
            command = SHELL + [str(PAYLOAD / 'usr/bin/bluemess-session-check')]
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for values in ({'SEAT': 'seat1'}, {'REMOTE': 'yes'}, {'TYPE': 'tty'},
                           {'VT': '0'}, {'VT': '8'}, {'SERVICE': 'greetd'}):
                with self.subTest(values=values):
                    result = subprocess.run(command, env=dict(env, **values), capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
