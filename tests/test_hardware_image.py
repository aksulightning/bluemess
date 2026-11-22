"""Image fixtures exercise missing firmware, compression and image-local symlinks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'build/check-hardware-image.py'
spec = importlib.util.spec_from_file_location('hardware_image', SCRIPT)
hardware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hardware)


class HardwareImage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.initrd = Path(self.temp.name) / 'initrd'
        for root in (self.root, self.initrd):
            (root / 'usr/lib/firmware/amdgpu').mkdir(parents=True)
            (root / 'lib').symlink_to('/usr/lib')

    def write(self, root, name, contents=b'firmware fixture'):
        path = root / 'usr/lib/firmware/amdgpu' / name
        path.write_bytes(contents)
        return path

    def test_both_images_must_contain_every_declared_stoney_file(self):
        declarations = ['amdgpu/stoney_ce.bin', 'amdgpu/stoney_pfp.bin', 'amdgpu/other.bin']
        for root in (self.root, self.initrd):
            self.write(root, 'stoney_ce.bin')
        self.write(self.root, 'stoney_pfp.bin')
        with self.assertRaisesRegex(hardware.ImageError, 'stoney_pfp'):
            hardware.check_firmware(self.root, self.initrd, declarations)
        self.write(self.initrd, 'stoney_pfp.bin')
        self.assertEqual(len(hardware.check_firmware(self.root, self.initrd, declarations)), 2)
        self.write(self.root, 'stoney_ce.bin', b'')
        with self.assertRaisesRegex(hardware.ImageError, 'stoney_ce'):
            hardware.check_firmware(self.root, self.initrd, declarations)

    def test_compressed_firmware_and_absolute_and_relative_symlinks(self):
        for suffix in ('', '.xz', '.zst'):
            with self.subTest(suffix=suffix):
                for root in (self.root, self.initrd):
                    self.write(root, 'shared.bin' + suffix)
                    link = root / 'usr/lib/firmware/amdgpu' / ('stoney_ce.bin' + suffix)
                    link.symlink_to('shared.bin' + suffix)
                result = hardware.check_firmware(self.root, self.initrd, ['amdgpu/stoney_ce.bin'])
                self.assertEqual(result[0]['initramfs'], 'usr/lib/firmware/amdgpu/shared.bin' + suffix)
                for root in (self.root, self.initrd):
                    (root / 'usr/lib/firmware/amdgpu' / ('stoney_ce.bin' + suffix)).unlink()

    def test_broken_symlink_and_loop_are_rejected(self):
        path = self.initrd / 'usr/lib/firmware/amdgpu/stoney_ce.bin'
        path.symlink_to('absent.bin')
        with self.assertRaises(hardware.ImageError):
            hardware.find_file(self.initrd, 'lib/firmware/amdgpu/stoney_ce.bin')
        path.unlink()
        path.symlink_to('stoney_ce.bin')
        with self.assertRaisesRegex(hardware.ImageError, 'loop'):
            hardware.find_file(self.initrd, 'lib/firmware/amdgpu/stoney_ce.bin')

    def test_absolute_symlinks_never_resolve_to_host_files(self):
        (self.root / 'outside').symlink_to('/etc/passwd')
        with self.assertRaises(hardware.ImageError):
            hardware.find_file(self.root, 'outside')
        with self.assertRaisesRegex(hardware.ImageError, 'escapes'):
            hardware.image_path(self.root, '../outside')

    def test_missing_profile_is_not_silently_accepted(self):
        with self.assertRaisesRegex(hardware.ImageError, 'no Stoney'):
            hardware.check_firmware(self.root, self.initrd, ['amdgpu/other.bin'])
