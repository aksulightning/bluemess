# Blue Mess Edition

A minimal Debian Sid amd64 desktop using **native OpenRC**, BusyBox ash, Xorg,
standalone Openbox, an XFCE panel and power manager, and XFCE Terminal. Greetd/tuigreet
provides console login on tty1, then `bluemess-desktop start` opens the desktop.
Desktop auto-start is an explicit per-user setting; normal password login remains.

**Development status:** first implementation. A specific image is validated only
when its Actions run passes all required checks. Consult
[the status record](docs/status.md) and that run before using an image. The 350 MiB desktop idle budget is an
acceptance target, not a measured claim or minimum physical RAM requirement.

## Download and verify

The verified workflow is archived at [`.github/oldworkflows/iso.yml`](.github/oldworkflows/iso.yml)
and no longer runs automatically. The tested downloads described below are
historical; current builds use the [untested workflow](#iso-without-tests-development-only).

On [Releases](https://github.com/aksulightning/bluemess/releases), look for the
`<commit-sha>-iso-tested` prerelease for the build you want. Each successful
verification on a push to `feat/blue-mess-edition` previously published the validated ISO
and reports under its full commit SHA. Download the ISO and `SHA256SUMS`
together. Published releases retain their original assets.

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

### ISO without tests (development only)

[Build installer ISO (untested)](https://github.com/aksulightning/bluemess/actions/workflows/build-iso.yml)
is a separate workflow that assembles the ISO without running `build/check.sh`,
`vm/verify.py` or the release validation gate. It runs on pushes to `main`,
`feat/**` and `fix/**` independently of the verified workflow. Manual
`workflow_dispatch` runs become available after the workflow exists on the
default branch.

When ISO assembly succeeds, the run uploads a
`blue-mess-edition-<version>-amd64-UNTESTED` artifact containing the ISO,
`SHA256SUMS`, and build provenance. Even if the full test workflow fails,
this artifact is available. An unsuccessful ISO assembly cannot produce a
usable ISO; its build logs are preserved instead.

Successful pushes or manual runs on `main` replace the
[`untested-refreshing` prerelease](https://github.com/aksulightning/bluemess/releases/tag/untested-refreshing)
with the same untested artifact.

**UNTESTED means no boot, installation, desktop or memory acceptance has
been established.** Use this download only for development testing. Verify
its checksum before trying it on disposable media or a VM.

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
Sign in at the tuigreet prompt on tty1 with the created account. It opens a
BusyBox ash login shell. Run `bluemess-desktop start` (or `startx`) to open
the desktop. tty2 and tty3 provide console logins; tty4 displays diagnostics
and has no login prompt. No other numbered TTY has a login service. The serial
console remains available for recovery and automated VM verification.
To start the desktop after future tty1 logins, run `bluemess-desktop auto-start true`
as your ordinary user, without sudo. Use `bluemess-desktop auto-start false` to
return to console-only logins, and `bluemess-desktop status` to inspect the setting.
Auto-start is off by default and never starts X on tty2/tty3, the serial console, SSH,
or as root. Leaving Openbox returns to the authenticated text console.

The bottom panel contains APP MENU, the terminal launcher, workspace switcher,
notification area, power indicator, clock and Window Buttons, in that order.
APP MENU uses Whisker Menu with a text-only button and opens All Applications.
There is no screensaver, automatic
screen locking, idle logout, idle suspend, dimming or display blanking by default.
Closing a laptop lid requests suspend through elogind; critical battery power
requests a controlled shutdown. Hardware support must be checked on real laptops.

Existing users keep their panel layout. Install `xfce4-whiskermenu-plugin`
with APT if needed, then run `xfce4-panel --add=whiskermenu` as your ordinary
user in an Openbox terminal. In the menu's Properties, select a title-only
panel button and set its title to `APP MENU`. In Panel Preferences → Items,
move Whisker Menu first and Window Buttons last; remove the old Applications
Menu if present. New users receive this layout by default.

XFCE Terminal is the default terminal, including the panel launcher,
Ctrl+Alt+T, Super+Enter and Openbox menu commands. Terminal launchers still
start BusyBox ash. New images select XFCE Terminal for `x-terminal-emulator`
and seed XFCE's terminal preference; xterm remains available as a fallback.
Existing users can install `xfce4-terminal` and select it with
`sudo update-alternatives --config x-terminal-emulator`. Existing panel and
Openbox settings are preserved: change their terminal commands to
`xfce4-terminal --execute /usr/bin/ash -l` to adopt the new launcher.

Terminal defaults disable the unsafe-paste confirmation dialog and the F10
menu shortcut, allowing F10 to reach programs such as htop. Existing users
can apply these settings from their desktop terminal without sudo:

```sh
xfconf-query -c xfce4-terminal -p /misc-show-unsafe-paste-dialog --create -t bool -s false
xfconf-query -c xfce4-terminal -p /shortcuts-no-menukey --create -t bool -s true
```

PipeWire, WirePlumber and PulseAudio/ALSA compatibility are included and start
automatically with the desktop. Closing a terminal leaves audio running;
leaving the desktop stops its audio processes. Use `bluemess-audio status`,
`bluemess-audio restart`, or `bluemess-audio test` as your ordinary user.
`bluemess-audio-panel` opens the output/profile/volume controls. Diagnostics
are saved in `~/.local/state/blue-mess/audio.log`.

`build-essential`, matching kernel headers, DKMS and Lua 5.4 are included for
local development and later driver installation. Debian's Openbox package
requires Python 3, so it remains installed as a dependency. No NVIDIA driver is
installed automatically.

Before installing GPU drivers, run `sudo bluemess-prepare-gpu-install` and
select NVIDIA or AMD. Confirm that system updates have been installed first.
The NVIDIA path prepares dependencies for the vendor `.run` installer, blocks
APT-managed NVIDIA packages, and disables Nouveau for the next boot. Reboot
before running the installer. The AMD path installs Debian firmware and Mesa
through APT. See [GPU preparation and undo instructions](docs/gpu-install.md).

Root is password-locked;
use `sudo`. BusyBox ash is the interactive shell; Debian Bash and dash remain.

## Build and verify

The active untested workflow builds inside a controlled Debian container on
GitHub-hosted `ubuntu-24.04` runners. The verified workflow is archived in
`.github/oldworkflows/iso.yml`; its pull-request and tag-triggered validation
and release jobs are disabled. Local static and QEMU/OVMF verification commands
remain available in the building guide.

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
