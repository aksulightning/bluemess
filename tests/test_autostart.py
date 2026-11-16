"""Real shell commands/locks/processes in temporary homes; never host boot scripts."""
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'packages/bme-config/root'
SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))


class Autostart(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.boot_id = self.root / 'boot-id'
        self.boot_id.write_text('aaaa-bbbb\n')
        self.script = self.root / 'runner'
        source = (PAYLOAD / 'usr/bin/bluemess-autostart').read_text()
        source = source.replace('/proc/sys/kernel/random/boot_id', str(self.boot_id))
        source = source.replace('/etc/blue-mess', str(self.root / 'etc/blue-mess'))
        source = source.replace('/var/lib/blue-mess', str(self.root / 'var/lib/blue-mess'))
        source = source.replace('/usr/bin/bluemess-autostart', str(self.script))
        self.script.write_text(source)
        self.script.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'),
                        XDG_STATE_HOME=str(self.home / '.local/state'),
                        PATH=str(self.bin) + ':' + os.environ['PATH'],
                        DISPLAY='', DBUS_SESSION_BUS_ADDRESS='', BME_AUTOSTART_TIMEOUT='3')
        # The same tests run under a root builder and an ordinary workstation.
        self.stub('id', 'echo "${FAKE_UID:-1000}"')
        self.stub('stat', '''
if [ "$2" = %u ]; then echo "${FAKE_UID:-1000}"; else exec /usr/bin/stat "$@"; fi
''')

    def stub(self, name, body):
        p = self.bin / name
        p.write_text('#!/bin/sh\n' + body + '\n')
        p.chmod(0o755)
        return p

    def job(self, name='10-test.sh', body='echo ran >> "$HOME/trace"', scope='boot'):
        directory = self.home / '.config/blue-mess' / ('boot.d' if scope == 'boot' else 'autostart.d')
        directory.mkdir(parents=True, exist_ok=True)
        p = directory / name
        p.write_text('#!/bin/sh\n' + body + '\n')
        p.chmod(0o755)
        return p

    def command(self, *args, **env):
        return subprocess.run(SHELL + [str(self.script), *args], env=dict(self.env, **env),
                              text=True, capture_output=True, timeout=10)

    def spawn(self, *args, **env):
        proc = subprocess.Popen(SHELL + [str(self.script), *args], env=dict(self.env, **env),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc

    def wait_file(self, path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(path.exists(), str(path))

    def test_boot_without_login_once_reboot_and_manual_retry(self):
        self.job(body='test -z "${DISPLAY:-}${DBUS_SESSION_BUS_ADDRESS:-}"; pwd >> "$HOME/trace"')
        for _ in range(2):
            p = self.command('boot')
            self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((self.home / 'trace').read_text().splitlines(), [str(self.home)])
        self.assertIn('completed this boot', self.command('status').stdout)
        self.boot_id.write_text('cccc-dddd\n')
        self.assertIn('pending this boot', self.command('status').stdout)
        self.assertEqual(self.command('boot').returncode, 0)
        self.assertEqual(self.command('boot', '--force').returncode, 0)
        self.assertEqual(len((self.home / 'trace').read_text().splitlines()), 3)
        self.assertTrue((self.home / '.local/state/blue-mess/autostart/boot/10-test.sh.log.old').exists())

    def test_desktop_scope_environment_and_full_logout(self):
        self.job(scope='desktop', body='printf "%s %s\\n" "$DISPLAY" "$DBUS_SESSION_BUS_ADDRESS" >> "$HOME/trace"')
        self.assertNotEqual(self.command('desktop').returncode, 0)
        self.assertFalse((self.home / 'trace').exists())
        self.assertEqual(self.command('boot').returncode, 0)
        for display in (':1', ':2'):
            runtime = self.root / ('runtime' + display[-1])
            runtime.mkdir()
            result = self.command('desktop', DISPLAY=display, DBUS_SESSION_BUS_ADDRESS='unix:path=session',
                                  XDG_RUNTIME_DIR=str(runtime))
            self.assertEqual(result.returncode, 0, result.stderr)
            runtime.rmdir()
        self.assertEqual((self.home / 'trace').read_text().splitlines(), [':1 unix:path=session'])
        self.assertNotEqual(self.command('desktop', FAKE_UID='0').returncode, 0)

    def test_order_skip_nonexecutables_and_continue_after_failure(self):
        self.job('20-last.sh', 'echo last >> "$HOME/trace"')
        self.job('10-fail.sh', 'echo first >> "$HOME/trace"; echo failure >&2; exit 7')
        self.job('00-disabled.sh').chmod(0o644)
        self.job('00-ignored.txt')
        for _ in range(2):
            self.assertNotEqual(self.command('boot').returncode, 0)
        self.assertEqual((self.home / 'trace').read_text().splitlines(), ['first', 'last'])
        status = self.command('status')
        self.assertIn('exited 7', status.stdout)
        self.assertIn('completed this boot', status.stdout)
        self.assertIn('failure', (self.home / '.local/state/blue-mess/autostart/boot/10-fail.sh.log').read_text())

    def test_timeout_and_stdin_do_not_block_following_jobs(self):
        self.job('10-hang.sh', 'sleep 20')
        self.job('20-read.sh', 'if read -r reply; then exit 1; fi; echo ran >> "$HOME/trace"')
        before = time.monotonic()
        result = self.command('boot', BME_AUTOSTART_TIMEOUT='1')
        self.assertLess(time.monotonic() - before, 5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exit 124', result.stdout)
        self.assertEqual((self.home / 'trace').read_text(), 'ran\n')

    def test_concurrent_runners_execute_only_once(self):
        self.job(body='echo ran >> "$HOME/trace"; sleep 1')
        first = self.spawn('boot')
        self.wait_file(self.home / 'trace')
        second = self.command('boot')
        self.assertNotEqual(second.returncode, 0)
        self.assertIn('another runner', second.stdout)
        first.communicate(timeout=5)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(self.command('boot').returncode, 0)
        self.assertEqual((self.home / 'trace').read_text(), 'ran\n')

    def test_interrupted_attempt_is_not_repeated_and_child_is_stopped(self):
        self.job(body='trap \'echo stopped > "$HOME/stopped"; exit 0\' TERM; echo ready > "$HOME/ready"; sleep 20')
        proc = self.spawn('boot')
        self.wait_file(self.home / 'ready')
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=8)
        self.wait_file(self.home / 'stopped')
        self.assertIn('started', self.command('status').stdout)
        self.assertNotEqual(self.command('boot').returncode, 0)

    def test_background_child_does_not_inherit_scope_lock(self):
        self.job(body='sleep 2 >/dev/null 2>&1 &')
        self.assertEqual(self.command('boot').returncode, 0)
        result = self.command('boot')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_directories_do_nothing_and_invalid_arguments_fail(self):
        self.assertEqual(self.command('boot').returncode, 0)
        self.assertFalse((self.home / '.local/state').exists())
        for args in [('bogus',), ('status', '--force'), ('boot', 'extra')]:
            self.assertEqual(self.command(*args).returncode, 2)
        for value in ['0', '-1', '001', '301', 'x', '9999999999999999999999']:
            self.assertNotEqual(self.command('boot', BME_AUTOSTART_TIMEOUT=value).returncode, 0)

    def test_root_scripts_require_safe_ownership_mode_and_no_symlink(self):
        jobs = self.root / 'etc/blue-mess/autostart.d'
        jobs.mkdir(parents=True)
        target = self.job(body='echo root-fixture > "$HOME/trace"')
        p = jobs / '10-test.sh'
        p.symlink_to(target)
        self.assertNotEqual(self.command('boot', FAKE_UID='0').returncode, 0)
        self.assertFalse((self.home / 'trace').exists())
        p.unlink()
        p.write_text(target.read_text())
        p.chmod(0o777)
        self.assertNotEqual(self.command('boot', FAKE_UID='0').returncode, 0)
        p.chmod(0o755)
        self.assertEqual(self.command('boot', FAKE_UID='0').returncode, 0)
        self.assertEqual((self.home / 'trace').read_text(), 'root-fixture\n')
        jobs.chmod(0o777)
        self.assertNotEqual(self.command('boot', FAKE_UID='0').returncode, 0)

    def test_admin_user_list_dispatches_after_privilege_drop_with_clean_environment(self):
        etc = self.root / 'etc/blue-mess'
        etc.mkdir(parents=True)
        (etc / 'autostart-users').write_text('# test\nalice\nroot\nbad user\nmissing\n')
        trace = self.root / 'dispatch'
        self.stub('getent', 'case "$2" in alice) echo "alice:x:1000:1000::' + str(self.home) + ': /bin/sh";; root) echo "root:x:0:0::/root:/bin/sh";; *) exit 2;; esac')
        # Only the runuser executable is replaced. Both env -i calls are real.
        runuser = self.stub('runuser', 'printf "%s\\n" "$@" > ' + shlex.quote(str(trace)) + '\nenv >> ' + shlex.quote(str(trace)))
        source = self.script.read_text().replace('runuser -u "$user"', str(runuser) + ' -u "$user"')
        self.script.write_text(source)
        result = self.command('boot', FAKE_UID='0', DISPLAY=':99', DBUS_SESSION_BUS_ADDRESS='wrong', EVIL='secret')
        self.assertNotEqual(result.returncode, 0)
        text = trace.read_text()
        self.assertIn('-u\nalice\n--\nenv\n-i\n', text)
        self.assertIn('HOME=' + str(self.home), text)
        self.assertIn('BME_AUTOSTART_TIMEOUT=3', text)
        self.assertNotIn('EVIL=', text)
        self.assertNotIn('DISPLAY=', text)
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS=', text)
        self.assertIn('expected an ordinary user', result.stderr)
        self.assertIn('invalid username', result.stderr)
        self.assertIn('unknown user', result.stderr)


class AutostartPackaging(unittest.TestCase):
    def test_upgrade_enables_once_without_running_jobs_and_preserves_admin_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(PAYLOAD, root, dirs_exist_ok=True)
            for path in ('etc/runlevels/sysinit', 'etc/runlevels/default', 'etc/init.d', 'bin'):
                (root / path).mkdir(parents=True, exist_ok=True)
            (root / 'etc/runlevels/sysinit/bme-root').symlink_to('/fixture/bme-root')
            (root / 'etc/adduser.conf').write_text('DSHELL=/bin/sh\n')
            users = root / 'etc/blue-mess/autostart-users'
            users.write_text('alice\n')
            conf = root / 'etc/conf.d/bme-autostart'
            conf.write_text('autostart_timeout=12\n')
            trace = root / 'trace'
            for name in ('add-shell', 'usermod', 'useradd', 'update-grub', 'pam-auth-update', 'dpkg-divert', 'rc-update'):
                p = root / 'bin' / name
                body = 'exit 0'
                if name == 'dpkg-divert':
                    body = 'echo bme-config'
                if name == 'rc-update':
                    body = 'echo "$*" >> ' + shlex.quote(str(trace)) + '\n' + (
                        'if [ "$1" = add ]; then ln -sfn /fixture/"$2" ' +
                        shlex.quote(str(root / 'etc/runlevels/default')) + '/"$2"; fi')
                p.write_text('#!/bin/sh\n' + body + '\n')
                p.chmod(0o755)
            busybox = root / 'usr/bin/busybox'
            busybox.write_text('#!/bin/sh\nprintf "ash\\nudhcpc\\nsyslogd\\nklogd\\ntimeout\\n"\n')
            busybox.chmod(0o755)
            runner = root / 'usr/bin/bluemess-autostart'
            runner.write_text('#!/bin/sh\necho FORBIDDEN >> ' + shlex.quote(str(trace)) + '\nexit 99\n')
            source = (ROOT / 'packages/bme-config/postinst').read_text()
            for prefix in ('/etc/', '/usr/', '/var/', '/boot/'):
                source = source.replace(prefix, str(root) + prefix)
            script = root / 'postinst'
            script.write_text(source)
            env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'])
            for iteration in range(2):
                result = subprocess.run(SHELL + [str(script), 'configure'], env=env,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                link = root / 'etc/runlevels/default/bme-autostart'
                if iteration == 0:
                    self.assertTrue(link.is_symlink())
                    link.unlink()  # Administrator disables it before the next upgrade.
                else:
                    self.assertFalse(link.is_symlink())
                self.assertEqual(users.read_text(), 'alice\n')
                self.assertEqual(conf.read_text(), 'autostart_timeout=12\n')
            self.assertEqual(trace.read_text().count('add bme-autostart default'), 1)
            self.assertNotIn('FORBIDDEN', trace.read_text())

    def test_target_activation_and_installer_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            chroot = bin_dir / 'chroot'
            chroot.write_text('#!/bin/sh\nexit 0\n')
            chroot.chmod(0o755)
            for role in ('installer', 'target'):
                image = root / role
                for p in ('etc', 'usr/share/blue-mess', 'etc/UPower', 'etc/init.d'):
                    (image / p).mkdir(parents=True, exist_ok=True)
                (image / 'usr/share/blue-mess/os-release').write_text('NAME=fixture\n')
                (image / 'etc/UPower/UPower.conf').write_text('CriticalPowerAction=PowerOff\n')
                (image / 'etc/init.d/greetd').touch(mode=0o755)
                result = subprocess.run(SHELL + [str(ROOT / 'config/configure-root.sh'), str(image), role],
                                        env=dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH']),
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((image / 'etc/runlevels/default/bme-autostart').is_symlink(), role == 'target')
