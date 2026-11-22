# HP Chromebook 11A G8 EE / Libreboot acceptance

Status: **physical-device validation not run**. Image-content and QEMU checks
must not be reported as an HP or Libreboot hardware pass.

The expected platform is the Barla/Careena AMD Stoney Ridge family. Confirm the
board identity, PCI IDs and actual firmware payload on the test machine.
[Libreboot's codename list](https://libreboot.org/docs/install/chromebook-codenames.html)
maps this model family; its [x86 documentation](https://libreboot.org/docs/install/chromebooks-x86.html)
describes EDK2/UEFI. Blue Mess currently supports amd64 UEFI. Legacy BIOS support
has not been added without evidence that this machine uses a legacy payload.

The live installer now includes `firmware-amd-graphics`, matching the target.
An initramfs hook includes AMDGPU and its available firmware without forcing
the module to load. Build reports verify every Stoney firmware name declared
by each shipped kernel in both roots and extracted initramfs images. They also
inventory USB/MMC/input modules and AMD microcode package status. Inspect that
inventory against the actual controllers; it is not a blanket driver guarantee.

New targets use agetty text login on tty1. This avoids the known default-startup
failure of the pinned Debian tuigreet binary; it does not repair tuigreet.
Existing users retain their selection. The optional greeter tests remain in
place and failures remain visible. Normal boot keeps kernel modesetting enabled.

Record these fields with the candidate's test evidence:

| Field | Result |
| --- | --- |
| Source commit / ISO SHA-256 | Pending candidate build |
| Board identity / GPU and storage PCI IDs | Not collected |
| Libreboot version / payload / UEFI mode | Not collected |
| Kernel / firmware package versions | Build reports; hardware confirmation pending |
| USB boot to visible installer login | Not tested on HP |
| Keyboard, touchpad, internal storage visibility | Not tested on HP |
| Offline installation and disk-only reboot | Not tested on HP |
| tty1 password login and Xorg/Openbox session | Not tested on HP |
| AMDGPU binding / renderer / missing firmware errors | Not tested on HP |
| Wi-Fi, audio, suspend/resume | Not tested on HP |

For a hardware test record, collect the firmware/board identification, kernel
command line, `lspci -nnk`, storage inventory, kernel firmware/DRM messages,
Xorg log and `glxinfo -B` from the authenticated desktop. Confirm a hardware
renderer rather than llvmpipe. Retain the successful normal-boot path; a
diagnostic `nomodeset` boot is not accelerated-graphics acceptance.

Classify failures by stage: firmware image discovery, kernel/graphics/storage,
installed bootloader, login manager, or desktop. The missing installer firmware
and the independently reproduced tuigreet failure are distinct defects.
Avoid changing ACPI or GPU parameters globally without a reproduced need.

Automated installation tests use only disposable QEMU disks created by
`vm/verify.py`. The existing USB and optical tests remain. Installed-disk boot
now starts with fresh OVMF variables and verifies the removable EFI fallback.
The physical record above remains separate from the full VM/350 MiB memory gate.
