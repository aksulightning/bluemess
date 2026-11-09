"""Isolated greeter readiness and OpenRC start-hook tests; no host service changes."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'packages/bme-config/root'
HELPER = PAYLOAD / 'usr/lib/blue-mess/greetd-ready'
SERVICE = PAYLOAD / 'usr/share/blue-mess/init.d/greetd'
SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))
# Resolve before fixtures prepend their fake busybox command to PATH.
SHELL[0] = shutil.which(SHELL[0]) or SHELL[0]


class GreeterFixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.trace = self.base / 'trace'
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        TRACE=str(self.trace), STATE=str(self.base / 'state'))

    def stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def run_shell(self, script, *args, **env):
        return subprocess.run(SHELL + ['-c', script, 'test', *map(str, args)],
                              env=dict(self.env, **env), capture_output=True,
                              text=True, timeout=20)


class Readiness(GreeterFixture):
    def setUp(self):
        super().setUp()
        self.stub('sleep', 'echo sleep >> "$TRACE"')
        self.stub('dbus-send', '''
echo "$*" >> "$TRACE"
n=0; [ ! -f "$STATE" ] || read -r n < "$STATE"
n=$((n+1)); echo "$n" > "$STATE"
[ "$n" -gt "${FAILURES:-0}" ]
''')

    def probe(self, tty_body='return 0', **env):
        return self.run_shell('helper=$1; set --; . "$helper"; '
                              'greetd_tty_ready() { ' + tty_body + '; }; '
                              'greetd_wait_ready', HELPER, **env)

    def test_ready_immediately_and_dbus_probe_is_bounded(self):
        result = self.probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('elogind replied', result.stdout)
        calls = self.trace.read_text().splitlines()
        self.assertEqual(len(calls), 1)
        for flag in ('--system', '--type=method_call', '--reply-timeout=1000',
                     '--dest=org.freedesktop.login1', 'org.freedesktop.DBus.Peer.Ping'):
            self.assertIn(flag, calls[0])

    def test_delayed_elogind_retries_without_log_flood(self):
        result = self.probe(FAILURES='3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count('elogind is not responding'), 1)
        self.assertEqual(self.trace.read_text().splitlines().count('sleep'), 3)

    def test_tty_readiness_precedes_dbus_and_logs_both_failures(self):
        result = self.probe('n=${n:-0}; n=$((n+1)); [ "$n" -gt 2 ]', FAILURES='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('tty1 is not yet', result.stderr)
        self.assertIn('elogind is not responding', result.stderr)
        self.assertEqual(self.trace.read_text().splitlines()[:2], ['sleep', 'sleep'])

    def test_real_tty_probe_rejects_missing_host_tty1(self):
        if Path('/dev/tty1').exists():
            self.skipTest('Host has tty1; never interact with it')
        result = self.run_shell('helper=$1; set --; . "$helper"; greetd_tty_ready', HELPER)
        self.assertNotEqual(result.returncode, 0)

    def test_missing_dbus_send_fails_without_waiting(self):
        (self.bin / 'dbus-send').unlink()
        shell = [shutil.which(SHELL[0]), *SHELL[1:]]
        result = subprocess.run(shell + [str(HELPER), '--wait'],
                                env=dict(self.env, PATH=str(self.bin)),
                                capture_output=True, text=True, timeout=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dbus-send is missing', result.stderr)
        self.assertFalse(self.trace.exists())

    def test_hung_probe_is_killed_by_outer_deadline(self):
        # Use the target timeout implementation when available. GNU timeout is
        # a local fallback, not evidence that the BusyBox target was tested.
        busybox = shutil.which('busybox')
        timeout = [busybox, 'timeout'] if busybox else [shutil.which('timeout')]
        self.assertIsNotNone(timeout[0])
        self.stub('dbus-send', 'exec /bin/sleep 60')
        script = 'helper=$1; set --; . "$helper"; greetd_tty_ready() { return 0; }; greetd_wait_ready'
        start = time.monotonic()
        process = subprocess.Popen(timeout + ['-s', 'KILL', '15'] + SHELL +
                                   ['-c', script, 'test', str(HELPER)], env=self.env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            status = process.wait(timeout=18)
        finally:
            # BusyBox can kill only the command; clean up the deliberately
            # noncompliant fake D-Bus child as well, using our private group.
            import signal
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        self.assertNotEqual(status, 0)
        self.assertGreaterEqual(time.monotonic() - start, 14)
        self.assertLess(time.monotonic() - start, 18)


class ServiceStart(GreeterFixture):
    def setUp(self):
        super().setUp()
        self.stub('rc-service', 'exit "${GETTY_STATUS:-1}"')
        self.stub('getent', 'exit "${ACCOUNT_STATUS:-0}"')
        self.stub('busybox', 'echo "probe $*" >> "$TRACE"; exit "${READY_STATUS:-0}"')
        self.stub('sleep', 'echo "delay $*" >> "$TRACE"; exit "${SLEEP_STATUS:-0}"')
        self.stub('tuigreet', 'exit 0')
        self.config = self.base / 'blue-mess.toml'
        self.config.touch()
        # Redirect filesystem prerequisites to fixtures, leaving hook logic intact.
        source = SERVICE.read_text().replace('/usr/bin/tuigreet', str(self.bin / 'tuigreet'))
        common = self.base / 'greeter-common'
        common.write_text('greeter_start_allowed() { return 0; }\n')
        source = source.replace('/usr/lib/blue-mess/greeter-common', str(common))
        source = source.replace('/etc/greetd/blue-mess.toml', str(self.config))
        source = source.replace('/etc/runlevels/default/bme-getty.tty1', str(self.base / 'getty-link'))
        self.service = self.base / 'greetd'
        self.service.write_text(source)

    def start(self, setting='', **env):
        return self.run_shell('eerror() { echo "$*" >&2; }; '
                              'einfo() { echo "$*"; }; ebegin() { echo "$*"; }; '
                              'eend() { return "$1"; }; . "$1"; ' + setting +
                              ' start_pre', self.service, **env)

    def test_default_delay_and_zero_override(self):
        for setting, expected in (('', '3'), ('greetd_start_delay=0;', None),
                                  ('greetd_start_delay=30;', '30')):
            with self.subTest(setting=setting):
                self.trace.unlink(missing_ok=True)
                result = self.start(setting)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = self.trace.read_text().splitlines()
                self.assertEqual(lines[0], 'probe timeout -s KILL 15 /usr/lib/blue-mess/greetd-ready --wait')
                self.assertEqual(lines[1:], [] if expected is None else ['delay ' + expected])

    def test_invalid_delay_is_rejected_before_probe(self):
        for delay in ('', '-1', '31', '99999999999999999999999', '01', '1.5', 'abc', '1 2'):
            with self.subTest(delay=delay):
                result = self.start('greetd_start_delay=' + shlex.quote(delay) + ';')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('integer from 0 to 30', result.stderr)
                self.assertFalse(self.trace.exists())

    def test_readiness_failure_skips_delay_and_reports_recovery(self):
        for status in ('1', '137'):
            with self.subTest(status=status):
                self.trace.unlink(missing_ok=True)
                result = self.start(READY_STATUS=status)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('delay ', self.trace.read_text())
                self.assertIn('rc-service greetd start', result.stderr)
                self.assertNotIn('Starting greetd', result.stdout)

    def test_getty_conflict_and_missing_account_or_config_fail_before_wait(self):
        for env in ({'GETTY_STATUS': '0'}, {'ACCOUNT_STATUS': '1'}):
            self.assertNotEqual(self.start(**env).returncode, 0)
            self.assertFalse(self.trace.exists())
        (self.base / 'getty-link').symlink_to('/nonexistent')
        self.assertNotEqual(self.start().returncode, 0)
        self.assertFalse(self.trace.exists())
        (self.base / 'getty-link').unlink()
        self.config.unlink()
        self.assertNotEqual(self.start().returncode, 0)
        self.assertFalse(self.trace.exists())

    def test_interrupted_delay_does_not_report_start(self):
        result = self.start(SLEEP_STATUS='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Starting greetd', result.stdout)


if __name__ == '__main__':
    unittest.main()
