"""Inspect built roots/initramfs, without loading modules or probing host hardware.

The Stoney Ridge profile is an image-content gate, not a physical-device test.
"""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


class ImageError(Exception):
    pass


def image_path(root, name):
    """Resolve absolute and relative image symlinks inside the image, not the host."""
    pending = deque(Path(name).parts)
    parts = []
    links = 0
    while pending:
        part = pending.popleft()
        if part == '/':
            parts = []
            continue
        if part in ('', '.'):
            continue
        if part == '..':
            if not parts:
                raise ImageError(f'Path escapes image: {name}')
            parts.pop()
            continue
        path = root.joinpath(*parts, part)
        if path.is_symlink():
            links += 1
            if links > 40:
                raise ImageError(f'Symlink loop in image: {name}')
            pending.extendleft(reversed(Path(os.readlink(path)).parts))
        else:
            parts.append(part)
    return root.joinpath(*parts)


def find_file(root, name, compressed=False):
    names = [name.lstrip('/')]
    if names[0].startswith('lib/'):
        names.append('usr/' + names[0])
    for candidate in names:
        for suffix in ('', '.xz', '.zst') if compressed else ('',):
            path = image_path(root, candidate + suffix)
            if path.is_file() and path.stat().st_size > 0:
                return str(path.relative_to(root))
    raise ImageError(f'Missing or empty image file: {name}')


def check_firmware(root, initramfs, declarations):
    firmware = sorted({name for name in declarations if name.startswith('amdgpu/stoney_')})
    if not firmware:
        raise ImageError('Kernel amdgpu module declares no Stoney Ridge firmware')
    return [dict(name=name,
                 root=find_file(root, 'lib/firmware/' + name, compressed=True),
                 initramfs=find_file(initramfs, 'lib/firmware/' + name, compressed=True))
            for name in firmware]


def chroot(root, *args, required=True):
    result = subprocess.run(['chroot', str(root), *args], text=True, capture_output=True)
    if result.returncode and required:
        raise ImageError(f'{args[0]} failed: {result.stderr.strip()}')
    return result.stdout.strip() if result.returncode == 0 else None


def check_kernel(root, kernel):
    if not re.fullmatch(r'[A-Za-z0-9.+_-]+', kernel):
        raise ImageError(f'Invalid kernel directory: {kernel}')
    module = chroot(root, 'modinfo', '-k', kernel, '-F', 'filename', 'amdgpu')
    firmware = chroot(root, 'modinfo', '-k', kernel, '-F', 'firmware', 'amdgpu').splitlines()
    initrd_name = find_file(root, f'boot/initrd.img-{kernel}')
    initrd = root / initrd_name
    with tempfile.TemporaryDirectory(prefix='bme-initramfs-') as temporary:
        extracted = Path(temporary)
        subprocess.run(['unmkinitramfs', str(initrd), str(extracted)], check=True)
        main = extracted / 'main' if (extracted / 'main').is_dir() else extracted
        if module != '(builtin)':
            find_file(root, module)
            find_file(main, module)
        checked_firmware = check_firmware(root, main, firmware)
        # Inventory these candidates; exact required modules depend on board/PCI
        # IDs. Do not infer HP compatibility from generic QEMU hardware.
        devices = {}
        for name in ('xhci_pci', 'xhci_hcd', 'usb_storage', 'uas', 'mmc_block',
                     'sdhci', 'sdhci_pci', 'sdhci_acpi', 'usbhid', 'hid_generic', 'atkbd'):
            path = chroot(root, 'modinfo', '-k', kernel, '-F', 'filename', name, required=False)
            present = path == '(builtin)'
            if path and not present:
                try:
                    find_file(main, path)
                    present = True
                except ImageError:
                    pass
            devices[name] = {'kernel_module': path, 'available_before_root': present}
    with initrd.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(kernel=kernel, amdgpu=module, initramfs=initrd_name,
                initramfs_sha256=digest, firmware=checked_firmware,
                storage_input_inventory=devices)


def inspect(root, role):
    status = chroot(root, 'dpkg-query', '-W', '-f=${db:Status-Status}', 'firmware-amd-graphics')
    if status != 'installed':
        raise ImageError('firmware-amd-graphics must be installed in both image roles')
    versions = sorted(p.name for p in image_path(root, 'lib/modules').iterdir() if p.is_dir())
    if not versions:
        raise ImageError('No kernel modules directory in image')
    microcode = chroot(root, 'dpkg-query', '-W', '-f=${db:Status-Status} ${Version}',
                       'amd64-microcode', required=False)
    return dict(status='passed', role=role, profile='amdgpu-stoney',
                firmware_package=chroot(root, 'dpkg-query', '-W', '-f=${Version}', 'firmware-amd-graphics'),
                amd64_microcode=microcode or 'not installed',
                kernels=[check_kernel(root, version) for version in versions])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--role', choices=('installer', 'target'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if root == Path('/'):
        parser.error('Refusing to inspect the host as an image')
    try:
        report = inspect(root, args.role)
    except (ImageError, OSError, subprocess.SubprocessError) as exc:
        report = dict(status='failed', role=args.role, error=str(exc))
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if report['status'] != 'passed':
        raise SystemExit(report['error'])
    print(f"{args.role}: AMDGPU and Stoney firmware verified in {len(report['kernels'])} initramfs image(s)")


if __name__ == '__main__':
    main()
