"""Run the VM service wait against isolated commands, never host services."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vm'))
import verify
import greeters

SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))


class ServiceReadiness(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.env = dict(os.environ, PATH=str(self.root) + ':' + os.environ['PATH'],
                        TRACE=str(self.root / 'trace'), COUNT=str(self.root / 'count'))
        self.stub('rc-service', '''
echo "rc-service $*" >> "$TRACE"
n=0; [ ! -f "$COUNT" ] || read -r n < "$COUNT"
n=$((n+1)); echo "$n" > "$COUNT"
if [ "$n" -le "${FAILURES:-0}" ]; then
    echo 'status: starting'
    exit "${STATUS:-8}"
fi
echo 'status: started'
''')
        self.stub('sleep', 'echo "sleep $*" >> "$TRACE"')
        self.stub('rc-status', 'echo "rc-status $*" >> "$TRACE"; echo boot-diagnostics')
        self.stub('tail', 'echo "tail $*" >> "$TRACE"; echo boot-log')
        self.guest = Mock()
        self.guest.run.side_effect = self.run_guest

    def stub(self, name, body):
        path = self.root / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def run_guest(self, command, timeout):
        self.assertEqual(timeout, 90)
        result = subprocess.run(SHELL + ['-c', command], env=self.env,
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise verify.Failure(result.stdout + result.stderr)
        return result.stdout

    def trace(self):
        return (self.root / 'trace').read_text().splitlines()

    def test_started_service_does_not_sleep(self):
        verify.wait_for_service(self.guest, 'greetd')
        self.assertEqual(self.trace(), ['rc-service greetd status'])

    def test_starting_service_is_retried_until_ready(self):
        self.env['FAILURES'] = '3'
        verify.wait_for_service(self.guest, 'greetd')
        self.assertEqual(self.trace().count('rc-service greetd status'), 4)
        self.assertEqual(self.trace().count('sleep 1'), 3)

    def test_never_ready_service_fails_with_diagnostics(self):
        for status in ('8', '3', '1'):
            with self.subTest(status=status):
                (self.root / 'count').unlink(missing_ok=True)
                (self.root / 'trace').unlink(missing_ok=True)
                self.env.update(FAILURES='999', STATUS=status)
                with self.assertRaisesRegex(verify.Failure, 'Timed out waiting.*greetd') as error:
                    verify.wait_for_service(self.guest, 'greetd')
                self.assertIn('boot-diagnostics', str(error.exception))
                self.assertIn('boot-log', str(error.exception))
                self.assertEqual(self.trace().count('sleep 1'), 60)
                self.assertEqual(self.trace().count('rc-service greetd status'), 61)

    def test_missing_service_command_cannot_pass(self):
        self.stub('rc-service', 'exit 127')
        with self.assertRaises(verify.Failure):
            verify.wait_for_service(self.guest, 'sddm')

    def test_root_state_waits_before_strict_assertions(self):
        self.env['FAILURES'] = '3'
        run_wait = self.run_guest

        def run(command, **kwargs):
            if kwargs:
                return run_wait(command, **kwargs)
            self.assertEqual((self.root / 'count').read_text().strip(), '5')
            self.assertIn('pgrep -x "$daemon"', command)
            raise verify.Failure('missing actual daemon')

        self.guest.run.side_effect = run
        with self.assertRaisesRegex(verify.Failure, 'missing actual daemon'):
            verify.root_state(self.guest, self.root, 'test')

    def test_root_state_stops_after_readiness_failure(self):
        self.env['FAILURES'] = '999'
        with self.assertRaises(verify.Failure):
            verify.root_state(self.guest, self.root, 'test')
        self.assertEqual(self.guest.run.call_count, 1)
        self.assertFalse((self.root / 'system-test.log').exists())

    def test_sddm_waits_before_greeter_assertions(self):
        events = []
        guest = Mock()
        guest.run.side_effect = lambda *args, **kwargs: events.append('assertions')
        with patch.object(greeters, 'wait_for_service', side_effect=lambda *args: events.append(args[1])), \
                patch.object(greeters.time, 'sleep'):
            greeters.sddm_prompt(guest, self.root, 'test')
        self.assertEqual(events, ['sddm', 'assertions'])


if __name__ == '__main__':
    unittest.main()
