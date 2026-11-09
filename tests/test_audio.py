"""Audio lifecycle tests use real child processes and simulated device commands."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'packages/bme-config/root/usr/bin/bluemess-audio'
SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))
MOCK = r"""
import json, os, pathlib, signal, sys, time
name = pathlib.Path(sys.argv[0]).name
root = pathlib.Path(os.environ['MOCK_AUDIO'])
def event(kind):
    with (root / 'events').open('a') as f:
        f.write(json.dumps([name, kind, os.getpid()]) + '\n')
def alive(daemon):
    try:
        os.kill(int((root / daemon).read_text()), 0)
        return True
    except (OSError, ValueError):
        return False
if name in ('pipewire', 'wireplumber', 'pipewire-pulse'):
    event('start')
    if name == os.environ.get('MOCK_FAIL'):
        sys.exit(1)
    if name != 'pipewire' and not alive('pipewire'):
        sys.exit(9)
    (root / name).write_text(str(os.getpid()))
    def stop(*args):
        (root / name).unlink(missing_ok=True)
        event('stop')
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    while True:
        time.sleep(.05)
elif name == 'pw-cli':
    sys.exit(0 if alive('pipewire') else 1)
elif name == 'pactl':
    if not alive('pipewire-pulse'):
        sys.exit(1)
    print(os.environ.get('MOCK_SINK', 'alsa_output.mock') if sys.argv[1] == 'get-default-sink' else 'PulseAudio (on PipeWire mock)')
elif name == 'wpctl':
    sys.exit(0 if alive('wireplumber') else 1)
elif name == 'pw-play':
    event('play')
elif name == 'pgrep':
    sys.exit(0 if os.environ.get('MOCK_EXISTING') else 1)
elif name == 'id':
    print(os.environ.get('MOCK_UID', '1000'))
elif name == 'stat':
    if sys.argv[2] == '%u':
        print('1000')
    else:
        os.execv('/usr/bin/stat', ['stat'] + sys.argv[1:])
"""

class AudioManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        binary = self.root / 'bin'
        binary.mkdir()
        for name in ('pipewire', 'wireplumber', 'pipewire-pulse', 'pw-cli',
                     'pactl', 'wpctl', 'pw-play', 'pgrep', 'id', 'stat'):
            p = binary / name
            p.write_text(f'#!{sys.executable}\n' + MOCK)
            p.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root), XDG_RUNTIME_DIR=str(self.runtime),
                        XDG_STATE_HOME=str(self.root / '.local/state'),
                        DBUS_SESSION_BUS_ADDRESS='unix:path=mock', MOCK_AUDIO=str(self.root),
                        PATH=str(binary) + ':' + os.environ['PATH'])
        self.managers = []
        self.addCleanup(self.stop_all)

    def command(self, action='status', **env):
        return subprocess.run(SHELL + [str(SCRIPT), action], env=dict(self.env, **env),
                              text=True, capture_output=True, timeout=60)

    def start(self, **env):
        process = subprocess.Popen(SHELL + [str(SCRIPT), 'run'], env=dict(self.env, **env),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.managers.append(process)
        return process

    def stop_all(self):
        for process in self.managers:
            if process.poll() is None:
                process.terminate()
                process.wait(15)

    def wait_for(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.1)
        self.fail('Timed out; audio log: ' + self.log())

    def log(self):
        p = self.root / '.local/state/blue-mess/audio.log'
        return p.read_text() if p.exists() else '(none)'

    def ready(self):
        return (self.runtime / 'blue-mess-audio/ready').exists()

    def pid(self, name):
        p = self.root / name
        return int(p.read_text()) if p.exists() else None

    def events(self):
        p = self.root / 'events'
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_start_order_duplicate_prevention_restart_and_cleanup(self):
        process = self.start()
        self.wait_for(self.ready)
        first = self.pid('pipewire')
        self.assertEqual(self.command().returncode, 0)
        duplicate = self.start()
        self.assertEqual(duplicate.wait(5), 0)
        self.assertEqual(self.pid('pipewire'), first)
        starts = [e[0] for e in self.events() if e[1] == 'start']
        self.assertEqual(starts[0], 'pipewire')
        self.assertCountEqual(starts[1:], ['wireplumber', 'pipewire-pulse'])
        result = self.command('restart')
        self.assertEqual(result.returncode, 0, result.stderr + self.log())
        self.assertNotEqual(self.pid('pipewire'), first)
        process.terminate()
        process.wait(15)
        for name in ('pipewire', 'wireplumber', 'pipewire-pulse'):
            self.assertIsNone(self.pid(name))
        self.assertNotEqual(self.command().returncode, 0)

    def test_child_failure_recovers_entire_stack(self):
        self.start()
        self.wait_for(self.ready)
        first = self.pid('pipewire')
        os.kill(self.pid('pipewire-pulse'), signal.SIGTERM)
        self.wait_for(lambda: self.ready() and self.pid('pipewire') not in (None, first))
        self.assertEqual(self.command().returncode, 0, self.log())

    def test_permanent_failure_has_bounded_retries(self):
        process = self.start(MOCK_FAIL='wireplumber')
        self.assertNotEqual(process.wait(35), 0)
        starts = [e for e in self.events() if e[:2] == ['wireplumber', 'start']]
        self.assertEqual(len(starts), 4)
        self.assertIn('repeatedly exited', self.log())
        self.assertFalse(self.ready())

    def test_refuses_root_insecure_runtime_missing_bus_and_unmanaged_server(self):
        for env in ({'MOCK_UID': '0'}, {'DBUS_SESSION_BUS_ADDRESS': ''},
                    {'XDG_RUNTIME_DIR': 'relative'}, {'MOCK_EXISTING': 'yes'}):
            with self.subTest(env=env):
                self.assertNotEqual(self.start(**env).wait(5), 0)
        self.runtime.chmod(0o755)
        self.assertNotEqual(self.command().returncode, 0)
        self.assertFalse(self.events())

    def test_dummy_output_is_failure_and_test_uses_pipewire(self):
        self.start()
        self.wait_for(self.ready)
        self.assertNotEqual(self.command(MOCK_SINK='auto_null').returncode, 0)
        self.assertEqual(self.command('test').returncode, 0)
        self.assertTrue(any(e[:2] == ['pw-play', 'play'] for e in self.events()))

    def test_restart_without_manager_fails(self):
        result = self.command('restart')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stopped', result.stderr)

