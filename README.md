# Blue Mess Edition

A minimal Debian Sid amd64 desktop using **native OpenRC**, BusyBox ash, Xorg,
standalone Openbox, an XFCE panel and power manager, and xterm. Console login,
then `bluemess-desktop start`. No display manager or compositor is required.
Desktop auto-start is an explicit per-user setting; normal password login remains.

**Development status:** first implementation. A specific image is validated only
when its Actions run passes all required checks. Consult
[the status record](docs/status.md) and that run before using an image. The 350 MiB desktop idle budget is an
acceptance target, not a measured claim or minimum physical RAM requirement.

## Download and verify

The first experimental release is [v0.1.0-alpha.1](https://github.com/aksulightning/bluemess/releases/tag/v0.1.0-alpha.1).
It is an **alpha for testing**, not a stable release. Each successful build of
`feat/blue-mess-edition` deletes and recreates this prerelease with the newly
validated ISO and reports. Its assets and checksums can change: download the ISO
and `SHA256SUMS` together. Version-tag releases retain their original assets.

Open [Actions](https://github.com/aksulightning/bluemess/actions/workflows/iso.yml)
and select a successful **Build and verify installer ISO** run. Download its
`blue-mess-edition-<version>-amd64-validated` artifact and extract the ZIP. GitHub
requires sign-in for Actions artifacts. Diagnostic artifacts are not installation
images. Validated artifacts are retained for 14 days; tag releases retain the
same tested bytes at [Releases](https://github.com/aksulightning/bluemess/releases).

```sh
sha256sum -c SHA256SUMS
```

Only a run that passed offline installation, boot from installed disk, actual
Xorg/Openbox session tests, package checks, and the three-boot memory benchmark
receives the validated artifact name. A failed memory target blocks publication.

## Install

Supported initial scope: **amd64 UEFI**, GPT, one FAT32 EFI System Partition and
one ext4 root, erasing the entire chosen disk. Disable Secure Boot. BIOS, dual
boot, encryption, and other architectures are future work.

Use a USB image writer to write the ISO to an entire USB device, or attach it as
an optical disk in a UEFI VM. Boot the installer and log in as `root`, password
`bluemess` (installer media only). Run:

```sh
bme-install --dry-run --disk /dev/CHOSEN_DISK
bme-install
```

The installer displays disk identifiers, refuses mounted/active disks and its
own backing disk, checks the payload before erasing, and requires a typed
`ERASE:/dev/CHOSEN_DISK` acknowledgement. Verify the disk identity carefully.
It prompts for host/user name, password, UTF-8 locale, keyboard layout, and
timezone. Installation is offline, from a separate clean payload. It does not
copy the live environment. Logs appear at the path printed by the installer and
are also copied to `/var/log/blue-mess/install.log` on success.

After completion, shut down, remove the installation medium, and boot the disk.
Log in with the created account, then run `bluemess-desktop start` (or `startx`).
To start the desktop after future tty1 logins, run `bluemess-desktop auto-start true`
as your ordinary user, without sudo. Use `bluemess-desktop auto-start false` to
return to console-only logins, and `bluemess-desktop status` to inspect the setting.
Auto-start is off by default and never starts X on tty2, the serial console, SSH,
or as root. Leaving Openbox returns to the authenticated text console.

The bottom panel contains a terminal launcher, window list, workspace switcher,
notification area, power indicator and clock. There is no screensaver, automatic
screen locking, idle logout, idle suspend, dimming or display blanking by default.
Closing a laptop lid requests suspend through elogind; critical battery power
requests a controlled shutdown. Hardware support must be checked on real laptops.

`build-essential`, matching kernel headers, DKMS and Lua 5.4 are included for
local development and later driver installation. Debian's Openbox package
requires Python 3, so it remains installed as a dependency. No NVIDIA driver is
installed automatically.

Root is password-locked;
use `sudo`. BusyBox ash is the interactive shell; Debian Bash and dash remain.

## Build and verify

GitHub-hosted `ubuntu-24.04` runners build inside a controlled Debian container
and run QEMU/OVMF with TCG, without requiring KVM or a self-hosted runner.
Pushes, pull requests, manual dispatch and `v*` tag pushes are supported. Manual
dispatch becomes available once this workflow has been merged to the default
branch. Initial development branch pushes run without waiting for dispatch.

See [building](docs/building.md), [architecture](docs/architecture.md),
[benchmark](docs/benchmark.md), and [troubleshooting](docs/troubleshooting.md).
The exact commands are also in [AGENTS.md](AGENTS.md).

## Update policy

Builds use one timestamped, signed Sid snapshot in `build/inputs.env`. Installed
systems track Debian **unstable**, including `non-free-firmware`, so Sid's
rolling changes and occasional package transitions apply. Review the proposed
changes before `sudo apt update && sudo apt full-upgrade`; keep backups and
recovery media. APT does not install recommends or suggests by default. Init
exclusions prevent switching to another PID 1 through dependency resolution.
Never bypass those exclusions to resolve an upgrade without investigating.

Copyright and licenses of Debian packages remain in `/usr/share/doc`; firmware
includes its upstream redistribution terms. Project code is MIT licensed.
