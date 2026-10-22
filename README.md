# Blue Mess Edition

A minimal Debian Sid amd64 desktop using **native OpenRC**, BusyBox ash, Xorg,
standalone Openbox, and xterm. Console login, then `startx`. No display manager,
panel, compositor, indexing service, or automatic desktop application startup.

**Development status:** first implementation; no validated ISO or memory result
has been produced yet. Consult [the status record](docs/status.md) and the actual
Actions run before using an image. The 150 MiB desktop idle budget is an
acceptance target, not a measured claim or minimum physical RAM requirement.

## Download and verify

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
Log in with the created account, then run `startx`. Root is password-locked;
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
