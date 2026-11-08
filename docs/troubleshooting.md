# Troubleshooting

- **No UEFI boot:** use amd64 UEFI with Secure Boot disabled. Check the ISO
  checksum. BIOS and Secure Boot are not supported in this version.
- **Installer refuses a disk:** inspect `lsblk -o NAME,SIZE,MODEL,SERIAL,MOUNTPOINTS`
  and `findmnt`. Unmount unrelated target filesystems and disable target swap.
  The running installation medium and its ancestors must never be selected.
- **Install failure:** use the printed private log path. It contains command
  errors but no passwords. Cleanup attempts all mounts, and reports anything
  still mounted. Do not boot a partially installed disk as a finished system.
- **Native boot failure:** use the serial console and `rc-status -a`,
  `readlink /proc/1/exe`, `dmesg`, and `/var/log/messages`. The expected PID 1
  is openrc-init, not systemd, SysVinit or BusyBox init.
- **X session failure:** log in as an ordinary user on a virtual terminal and
  run `startx`; inspect `~/.local/share/xorg/Xorg.0.log`, `loginctl`, and
  `rc-service dbus status` / `rc-service elogind status`. Do not run the desktop
  as root or use Xvfb to bypass device/session failures.
- **Networking:** inspect `ip link`, `ip addr`, `ip route`, `/etc/resolv.conf`,
  and `rc-status`. See architecture documentation for wired/Wi-Fi setup.
- **APT upgrade conflict:** run `sudo dpkg --audit` and `sudo apt-get check`.
  Do not remove the init pin or replace service commands with success stubs.
- **CI failed:** diagnostic artifacts retain build, installer and VM logs even
  on failure. A candidate ISO existing on disk is not proof it can install or
  meet the memory target. Start with the failed assertion and serial log.

The first reference benchmark measures desktop usage in a 1 GiB VM; installer
minimum physical memory and a broad hardware compatibility matrix have not yet
been established. Installer observations are reported separately by VM tooling.

## Local login and seat access

Sign in at tuigreet as your ordinary user on the machine's tty1, then run
`bluemess-desktop start` from that login. Run `bluemess-session-check`
from tty1 or an Openbox terminal to inspect that process's session.

If tty1 has no greeter, use tty2 or the serial console to log in and check
`rc-service greetd status` and `/var/log/rc.log`. The installed system uses
`/etc/greetd/blue-mess.toml` for tty1 and Debian's `/etc/pam.d/greetd` for
authentication. When upgrading an earlier installation, install `greetd`
and `tuigreet` before configuring the updated `bme-config` package.
The package switches the default runlevel to greetd for the next boot.

The checker verifies a local, active tty1 session on `seat0` and an
`XDG_RUNTIME_DIR` matching elogind's path, owned by the user and set to
mode `0700`. In the desktop it also queries the session D-Bus. It reports
direct graphics and audio device access, X11 and PulseAudio socket
information, and any inaccessible dconf runtime directory.

Manual and automatic starts through `bluemess-desktop` record the
pre-Xorg check in `~/.local/state/blue-mess/login-check.log`. The packaged
Openbox session records a second check after D-Bus starts in
`~/.local/state/blue-mess/desktop.log`, including when invoked through
the default `startx` setup. Set `XDG_STATE_HOME` to choose the parent
state directory. These checks report issues and let startup proceed.
For more seat details, run `loginctl seat-status seat0`.

Older Blue Mess builds passed `--resolve-names=never` to udev. This
skipped the group assignments in Debian's device rules, including
`input`, `audio`, `video`, and `render`. If your installed
`/etc/init.d/udev` still contains that option, remove the
`command_args="--resolve-names=never"` line and reboot to apply Debian's
default name resolution and recreate the device nodes.
[Debian udev manual](https://manpages.debian.org/unstable/udev/systemd-udevd.8.en.html)

## NVIDIA driver loads but Xorg fails

Check `uname -r`, `dkms status`, `nvidia-smi` and `loginctl session-status` from
tty1. In the observed RTX 3060 failure, the DKMS version matched the running
kernel, `nvidia-smi` saw the GPU, and elogind handed Xorg the primary DRM node
(`/dev/dri/card0`). NVIDIA then reported denied access to the render node,
followed by `Failed to acquire modesetting permission` and `no screens found`.

```sh
id -nG
ls -l /dev/dri/renderD*
```

If the NVIDIA render node is `root:root` with mode `0660`, check the
[udev setting above](#local-login-and-seat-access) so the node can receive
the `render` group.
For a quick test, if your user belongs to `video`, run
`sudo chgrp video /dev/dri/renderD128` and retry `bluemess-desktop start`. Use
the actual NVIDIA render node from `/dev/dri/by-path/` if its number differs.
The temporary group change is lost when udev recreates the node.

If the node is `root:render` with mode `0660` and your user still cannot
open it, add your account to `render`.

```sh
sudo usermod -aG render "$(id -un)"
```

Log out and back in, then confirm `id -nG` includes `render`.

### X11 socket ownership

If Xorg warns that `/tmp/.X11-unix` should be owned by root, apply an explicit
tmpfiles rule. Debian's standalone tmpfiles package supplies the executable,
while the X11 rule ships in the full systemd package. A prefix filter alone
requires an existing rule. This warning is separate from NVIDIA device access.
[Debian package file lists](https://packages.debian.org/sid/amd64/systemd-standalone-tmpfiles/filelist)

```sh
printf '%s\n' 'd /tmp/.X11-unix 1777 root root -' |
    sudo systemd-tmpfiles --create -
```

## Sound in Openbox

Install PipeWire with PulseAudio and ALSA compatibility, WirePlumber, and a
volume control.
[Debian PipeWire audio package](https://packages.debian.org/sid/pipewire-audio)

```sh
sudo apt install pipewire-audio pulseaudio-utils pavucontrol
```

From an Openbox terminal, run `bluemess-start-audio` as your regular user.
It waits for PipeWire before starting WirePlumber and `pipewire-pulse`.
The sockets live at `$XDG_RUNTIME_DIR/pipewire-0` and
`$XDG_RUNTIME_DIR/pulse/native`. If the PulseAudio socket already responds,
the command reports the running server and exits. Stop any incomplete
manual audio session before starting a new one. Keep the terminal open
while using the new session. Press Ctrl+C there to stop the processes it
started. The earlier command name `bluemess-audio-start` is an alias.

The launcher uses the inherited session D-Bus address when available. If
that address is unset, it starts a private bus for the lifetime of the
audio launcher. With an older launcher, run
`dbus-run-session -- bluemess-start-audio` from the Openbox terminal to
supply a bus. [D-Bus session runner manual](https://dbus.freedesktop.org/doc/dbus-run-session.1.html)

The launcher falls back to the existing `/run/user/$(id -u)` login directory
if `XDG_RUNTIME_DIR` is unusable. If neither directory is usable, check
`ls -ld "/run/user/$(id -u)"` and `loginctl session-status` from your regular
user session. Elogind creates and owns the lifecycle of that directory.
[Debian pam_elogind manual](https://manpages.debian.org/unstable/libpam-elogind/pam_elogind.8.en.html)

Run `bluemess-audio-panel` from a second Openbox terminal to open
`pavucontrol` against a responding server. It checks `PULSE_SERVER`,
`PULSE_RUNTIME_PATH`, `XDG_RUNTIME_DIR` and the login runtime directory.
Select and unmute the intended output under **Output Devices**. If an
application is already playing, check its route under **Playback**.

`bluemess-fix-audio detect` shows ALSA cards, the connected server, available
card profiles, and current playback outputs. `bluemess-fix-audio server`
prints the server address alone.

If only NVIDIA HDMI is active and you want speakers plugged into the PC,
use the profile shown by `detect` for your onboard audio card. For example,
the reported Intel PCH card with an ALC897 codec can use this command when
`output:analog-stereo` is available.

```sh
bluemess-fix-audio enable alsa_card.pci-0000_00_1f.3 output:analog-stereo
bluemess-audio-panel
```

`bluemess-fix-audio disable CARD` selects the `off` profile for that card.
This disables both its inputs and outputs. Use `enable CARD PROFILE` to
restore a profile. The panel lets you select the default playback output.
[Debian pactl manual](https://manpages.debian.org/unstable/pulseaudio-utils/pactl.1.en.html)

On an older installation, copy the three [audio commands](../packages/bme-config/root/usr/bin/)
into the same directory, make them executable, and run them with `./`.

For manual startup, `Host is down` means a client could not reach the
PipeWire core. Start `pipewire` in the foreground, then check
`pw-cli info 0` from a second terminal in the same desktop session.
RTKit `ServiceUnknown` warnings concern real-time scheduling. A successful
core query confirms the server is reachable.
[PipeWire daemon documentation](https://docs.pipewire.org/page_daemon.html)
