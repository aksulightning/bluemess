"""Exercise GPU preparation in temporary roots with mocked package operations."""
import json
import fcntl
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'packages/bme-config/root/usr/bin/bluemess-prepare-gpu-install'
SHELL = shlex.split(os.environ.get('BME_TEST_SHELL', 'dash'))
KERNEL = '6.1.0-fixture-amd64'
PIN = 'etc/apt/preferences.d/00blue-mess-nvidia-run.pref'
NOUVEAU = 'etc/modprobe.d/blue-mess-disable-nouveau.conf'

STUB = r'''
import json, os, pathlib, sys
root = pathlib.Path(os.environ['FIXTURE'])
tool = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / 'calls').open('a') as f:
    f.write(json.dumps([tool] + args) + '\n')
if tool == 'id':
    print(os.environ.get('TEST_UID', '0'))
elif tool == 'uname':
    print('6.1.0-fixture-amd64')
elif tool == 'dpkg':
    if args == ['--print-architecture']:
        print(os.environ.get('ARCH', 'amd64'))
    elif args == ['--audit']:
        print(os.environ.get('AUDIT', ''), end='')
    elif args == ['--print-foreign-architectures']:
        print('i386' if (root / 'i386').exists() else '')
    elif args == ['--add-architecture', 'i386']:
        (root / 'i386').touch()
    else:
        sys.exit(90)
elif tool == 'dpkg-query':
    print(os.environ.get('PACKAGES', 'libglvnd-dev installed'))
elif tool == 'apt-get':
    if 'check' in args and os.environ.get('CHECK_FAIL'):
        sys.exit(1)
    if 'update' in args and os.environ.get('UPDATE_FAIL'):
        sys.exit(1)
    if '--simulate' in args and os.environ.get('SIMULATE_FAIL'):
        sys.exit(1)
    if 'install' in args and '--simulate' not in args:
        if os.environ.get('INSTALL_FAIL'):
            sys.exit(1)
        if not os.environ.get('MISSING_HEADERS'):
            header = root / 'lib/modules/6.1.0-fixture-amd64/build/Makefile'
            header.parent.mkdir(parents=True, exist_ok=True)
            header.touch()
elif tool == 'update-initramfs':
    if os.environ.get('INITRAMFS_FAIL'):
        sys.exit(1)
else:
    sys.exit(91)
'''


class GPUPreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        binary = self.root / 'bin'
        binary.mkdir()
        shim = binary / 'shim'
        shim.write_text('#!' + sys.executable + '\n' + STUB)
        shim.chmod(0o755)
        for tool in ('id', 'uname', 'dpkg', 'dpkg-query', 'apt-get', 'update-initramfs'):
            (binary / tool).symlink_to('shim')
        # Rewrite only the copied script's filesystem paths; production has
        # no test flags, root override, or bypass of its privilege check.
        source = SCRIPT.read_text()
        for prefix in ('/etc/', '/run/', '/lib/modules/'):
            source = source.replace(prefix, str(self.root) + prefix)
        self.script = self.root / 'prepare'
        self.script.write_text(source)
        self.env = dict(os.environ, FIXTURE=str(self.root),
                        PATH=str(binary) + ':' + os.environ['PATH'])

    def run_prepare(self, gpu='nvidia', answer='y\n', **env):
        return subprocess.run(SHELL + [str(self.script)] + ([gpu] if gpu else []),
                              input=answer, text=True, capture_output=True,
                              env=dict(self.env, **env))

    def calls(self):
        path = self.root / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_nvidia_packages_policy_headers_blacklist_and_order(self):
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        installs = [c for c in calls if c[0] == 'apt-get' and 'install' in c]
        self.assertEqual(len(installs), 2)
        self.assertIn('--simulate', installs[0])
        self.assertNotIn('--simulate', installs[1])
        for c in installs:
            for pkg in ('build-essential', 'dkms', 'pkg-config', 'libglvnd-dev',
                        'libglvnd-dev:i386', 'linux-headers-' + KERNEL):
                self.assertIn(pkg, c)
            self.assertIn('--no-remove', c)
            self.assertIn('--no-install-recommends', c)
        self.assertLess(calls.index(['dpkg', '--add-architecture', 'i386']),
                        next(i for i, c in enumerate(calls) if c[0] == 'apt-get' and 'update' in c))
        self.assertLess(calls.index(installs[1]), calls.index(['update-initramfs', '-u', '-k', 'all']))
        self.assertIn('Pin-Priority: -1', (self.root / PIN).read_text())
        self.assertIn('blacklist nouveau\noptions nouveau modeset=0', (self.root / NOUVEAU).read_text())
        self.assertIn('Reboot before', result.stdout)
        self.assertIn('NOT been downloaded or started', result.stdout)

    def test_amd_uses_apt_without_nvidia_settings_or_multiarch(self):
        result = self.run_prepare('amd')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / PIN).exists())
        self.assertFalse((self.root / NOUVEAU).exists())
        self.assertFalse((self.root / 'i386').exists())
        install = next(c for c in self.calls() if c[0] == 'apt-get' and 'install' in c)
        for package in ('firmware-amd-graphics', 'libgl1-mesa-dri', 'libglx-mesa0',
                        'mesa-vulkan-drivers', 'xserver-xorg-video-amdgpu'):
            self.assertIn(package, install)

    def test_no_confirmation_makes_no_changes(self):
        for answer in ('n\n', '', 'invalid\nn\n'):
            with self.subTest(answer=answer):
                result = self.run_prepare(answer=answer)
                self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(c[0] in ('id', 'dpkg') for c in self.calls()))
        self.assertFalse((self.root / 'etc').exists())

    def test_interactive_vendor_and_invalid_confirmation(self):
        result = self.run_prepare('', answer='AMD\nmaybe\nY\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Please answer y or n.', result.stdout)

    def test_root_architecture_and_vendor_guards(self):
        for gpu, env in [('nvidia', {'TEST_UID': '1000'}),
                         ('nvidia', {'ARCH': 'arm64'}), ('intel', {})]:
            with self.subTest(gpu=gpu, env=env):
                self.assertNotEqual(self.run_prepare(gpu, **env).returncode, 0)
        self.assertFalse((self.root / 'etc').exists())

    def test_broken_package_state_stops_before_changes(self):
        for env in ({'AUDIT': 'unconfigured package'}, {'CHECK_FAIL': '1'}):
            with self.subTest(env=env):
                self.assertNotEqual(self.run_prepare(**env).returncode, 0)
                self.assertFalse((self.root / PIN).exists())
                self.assertFalse((self.root / 'i386').exists())

    def test_existing_nvidia_packages_are_not_removed(self):
        for package in ('nvidia-driver', 'nvidia-open-kernel-dkms',
                        'libnvidia-glcore:i386', 'libcuda1', 'libglx-nvidia0'):
            with self.subTest(package=package):
                result = self.run_prepare(PACKAGES=package + ' installed')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(package, result.stderr)
                self.assertFalse((self.root / PIN).exists())
        self.assertFalse(any('remove' in c or 'purge' in c for c in self.calls()))

    def test_residual_nvidia_configuration_does_not_block(self):
        self.assertEqual(self.run_prepare(PACKAGES='nvidia-driver config-files').returncode, 0)

    def test_dependency_failures_do_not_disable_nouveau(self):
        for key in ('UPDATE_FAIL', 'SIMULATE_FAIL', 'INSTALL_FAIL', 'MISSING_HEADERS'):
            with self.subTest(key=key):
                header = self.root / ('lib/modules/' + KERNEL + '/build/Makefile')
                if header.exists():
                    header.unlink()
                self.assertNotEqual(self.run_prepare(**{key: '1'}).returncode, 0)
                self.assertFalse((self.root / NOUVEAU).exists())
        self.assertFalse(any(c[0] == 'update-initramfs' for c in self.calls()))

    def test_initramfs_failure_requires_repair_then_can_rerun(self):
        result = self.run_prepare(INITRAMFS_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Do not reboot', result.stderr)
        self.assertNotIn('NVIDIA prerequisites installed', result.stdout)
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.calls().count(['dpkg', '--add-architecture', 'i386']), 1)

    def test_repeated_run_preserves_identical_configuration(self):
        self.assertEqual(self.run_prepare().returncode, 0)
        before = [(self.root / p).stat().st_ino for p in (PIN, NOUVEAU)]
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(before, [(self.root / p).stat().st_ino for p in (PIN, NOUVEAU)])
        self.assertEqual(self.calls().count(['dpkg', '--add-architecture', 'i386']), 1)

    def test_existing_custom_policy_is_preserved(self):
        pin = self.root / PIN
        pin.parent.mkdir(parents=True)
        pin.write_text('administrator policy\n')
        self.assertNotEqual(self.run_prepare().returncode, 0)
        self.assertEqual(pin.read_text(), 'administrator policy\n')
        self.assertFalse((self.root / NOUVEAU).exists())
        self.assertEqual(list(pin.parent.glob('*.??????')), [])

    def test_config_symlink_is_not_followed(self):
        pin = self.root / PIN
        pin.parent.mkdir(parents=True)
        target = self.root / 'protected'
        target.write_text('preserve me')
        pin.symlink_to(target)
        self.assertNotEqual(self.run_prepare().returncode, 0)
        self.assertEqual(target.read_text(), 'preserve me')

    def test_concurrent_preparation_stops_before_apt(self):
        lock = self.root / 'run/bluemess-prepare-gpu-install.lock'
        lock.parent.mkdir()
        with lock.open('w') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already running', result.stderr)
        self.assertFalse(any(c[0] == 'apt-get' for c in self.calls()))

    def test_amd_preserves_previous_nvidia_preparation(self):
        for path in (PIN, NOUVEAU):
            file = self.root / path
            file.parent.mkdir(parents=True)
            file.write_text('previous configuration\n')
        result = self.run_prepare('amd')
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in (PIN, NOUVEAU):
            self.assertEqual((self.root / path).read_text(), 'previous configuration\n')

    def test_amd_failure_is_not_reported_as_success(self):
        for key in ('UPDATE_FAIL', 'SIMULATE_FAIL', 'INSTALL_FAIL', 'INITRAMFS_FAIL'):
            with self.subTest(key=key):
                result = self.run_prepare('amd', **{key: '1'})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('AMD firmware and Mesa installed', result.stdout)

    @unittest.skipUnless(shutil.which('apt-cache'), 'APT policy parser unavailable')
    def test_real_apt_policy_blocks_nvidia_but_allows_prerequisites_on_both_arches(self):
        self.assertEqual(self.run_prepare().returncode, 0)
        lists = self.root / 'lists'
        lists.mkdir()
        (self.root / 'status').touch()
        (self.root / 'sources.list').write_text('deb http://fixture.invalid sid main\n')
        packages = ('nvidia-driver', 'nvidia-open-kernel-dkms', 'libnvidia-glcore',
                    'libcuda1', 'libglx-nvidia0', 'libnvcuvid1', 'libnvoptix1',
                    'libglvnd-dev', 'build-essential', 'dkms', 'pkg-config',
                    'libgl1-mesa-dri', 'firmware-amd-graphics')
        for arch in ('amd64', 'i386'):
            (lists / ('fixture.invalid_dists_sid_main_binary-' + arch + '_Packages')).write_text(
                ''.join('Package: ' + p + '\nVersion: 1.0\nArchitecture: ' + arch +
                        '\nDescription: fixture\n\n' for p in packages))
        options = ['-o', 'Dir::State::status=' + str(self.root / 'status'),
                   '-o', 'Dir::State::lists=' + str(lists),
                   '-o', 'Dir::Etc::sourcelist=' + str(self.root / 'sources.list'),
                   '-o', 'Dir::Etc::sourceparts=-', '-o', 'Dir::Etc::preferences=-',
                   '-o', 'Dir::Etc::preferencesparts=' + str((self.root / PIN).parent),
                   '-o', 'Dir::Cache::pkgcache=', '-o', 'Dir::Cache::srcpkgcache=',
                   '-o', 'APT::Architecture=amd64', '-o', 'APT::Architectures::=amd64',
                   '-o', 'APT::Architectures::=i386']
        for arch in ('amd64', 'i386'):
            for package in packages:
                with self.subTest(package=package, arch=arch):
                    result = subprocess.run(['apt-cache'] + options + ['policy', package + ':' + arch],
                                            text=True, capture_output=True,
                                            env=dict(os.environ, LC_ALL='C'), check=True)
                    blocked = package in packages[:7]
                    self.assertIn('Candidate: ' + ('(none)' if blocked else '1.0'), result.stdout)
