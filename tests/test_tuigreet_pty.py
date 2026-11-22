"""Real PTY child exits retain diagnostics and never pass the startup gate."""
import importlib.util
import os
from pathlib import Path
import pty
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'build/check-tuigreet-pty.py'
spec = importlib.util.spec_from_file_location('tuigreet_pty', SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class TerminalStartup(unittest.TestCase):
    def run_exit(self, message, code, already_exited=False):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        process = subprocess.Popen(
            [sys.executable, '-c',
             'import sys; sys.stderr.write(sys.argv[1]); sys.exit(int(sys.argv[2]))',
             message, str(code)], stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        self.addCleanup(process.wait)
        if already_exited:
            process.wait(timeout=5)
        with self.assertRaises(AssertionError) as error:
            checker.check_startup(process, master, 0)
        process.wait(timeout=5)
        self.assertIn(message, str(error.exception))
        self.assertIn(f'exit status {code}', str(error.exception))

    def test_crash_output_is_retained_even_if_child_has_already_exited(self):
        self.run_exit('terminal startup panic', 101, already_exited=True)

    def test_early_clean_exit_without_ui_is_still_failure(self):
        self.run_exit('exiting before rendering', 0)


if __name__ == '__main__':
    unittest.main()
