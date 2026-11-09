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

If tty1 has no greeter, use tty2, tty3 or the serial console to log in and check
`rc-service greetd status` and `/var/log/rc.log`. The installed system uses
`/etc/greetd/blue-mess.toml` for tty1 and Debian's `/etc/pam.d/greetd` for
authentication. When upgrading an earlier installation, install `greetd`
and `tuigreet` before configuring the updated `bme-config` package.
The package switches the default runlevel to greetd for the next boot.

### Greeter startup readiness and delay

The native OpenRC service waits up to 15 seconds for `/dev/tty1` to be an
accessible character device and for elogind to answer a system D-Bus ping.
Each D-Bus call has a one-second reply timeout; an outer BusyBox timeout
bounds the whole readiness phase. Missing programs, configuration or the
`_greetd` account fail immediately. A competing tty1 getty also blocks startup.
The existing udev service already settles coldplug before elogind starts;
this additional check tests that elogind actually responds.

After readiness, `/etc/conf.d/greetd` controls an additional settling delay:

```sh
greetd_start_delay=3
```

Use an integer from `0` to `30` seconds. `0` disables only the extra delay;
the readiness check remains enabled. Empty or malformed values fail startup.
The three-second default is a configurable timing workaround, not proof that
a GPU/console rendering problem is fixed. There is no requirement for a
particular DRM card or framebuffer device.

The hook runs on service start or explicit restart. Normal login/logout and
OpenRC crash respawns do not repeat it. Existing supervision still waits two
seconds between daemon respawns and limits them to five within 60 seconds.
There is no recurring greeter health check that could mistake an authenticated
shell or desktop for a missing tuigreet process.

On failure, inspect `/var/log/rc.log` for the readiness reason and
`/var/log/messages` for daemon output. A readiness timeout leaves greetd
unstarted; after correcting tty1, D-Bus or elogind, run from tty2 or tty3:

```sh
sudo rc-service greetd start
```

To apply a delay change to an already running service, log out of the tty1
desktop **and its login shell** first, then use tty2 or tty3:

```sh
sudo rc-service greetd restart
```

Do not restart greetd while a tty1 user session is running. Package upgrades
install the new hook for the next service start without restarting greetd.
`/etc/conf.d/greetd` is a Debian conffile, so local delay settings are preserved
through the normal package configuration-file handling. This change does not
require replacing the existing `/etc/greetd/blue-mess.toml`.

### Greeter clock workaround

The default tuigreet command includes a seconds clock so its normal render
timer produces changing terminal output without a keypress. This is a display
workaround, not a forced full-screen repaint or a hardware validation result.
For an existing installation, edit `/etc/greetd/blue-mess.toml` and set the
`command` under `[default_session]` to:

```toml
command = "/usr/bin/tuigreet --time --time-format '%H:%M:%S' --cmd '/usr/bin/ash -il'"
```

While tty1 is at the greeter, apply it from tty2 or SSH with
`sudo rc-service greetd restart`. The configuration is a Debian conffile;
package upgrades may preserve local edits rather than adopting this command.
Tuigreet remains the greeter; no synthetic keys or extra background service
are used. The clock does not guarantee recovery from every blank-screen cause.

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

New images include PipeWire, WirePlumber, PulseAudio/ALSA compatibility,
ALSA UCM profiles, Intel/SOF audio firmware and pavucontrol. The desktop
starts one audio supervisor automatically on its own D-Bus session. Closing
a terminal does not stop audio. Desktop logout stops the three audio daemons.

As your regular user, without sudo:

```sh
bluemess-audio status
bluemess-audio test
bluemess-audio-panel
```

The test plays a short sample through PipeWire. It preserves the current
mute and volume settings. Select and unmute the intended output under
**Output Devices**; check **Playback** for an application's route and
**Configuration** for disabled card profiles. A dummy output is a failure,
not evidence of working audio. A VM must expose a sound card and have a
working host audio backend.

If a daemon has failed, the manager retries up to three times. Request a
fresh stack with `bluemess-audio restart`. The older `bluemess-start-audio`
and `bluemess-audio-start` names now request that same restart. If the
manager has exhausted its retries, inspect the log and restart the desktop.

```sh
cat ~/.local/state/blue-mess/audio.log
bluemess-session-check
cat /proc/asound/cards
aplay -l
sudo dmesg | grep -Ei 'snd|sof|audio|firmware'
```

`XDG_RUNTIME_DIR` must refer to the user's private mode-0700 elogind runtime
directory. Do not create a shared replacement or run PipeWire with sudo.
The sockets live at `$XDG_RUNTIME_DIR/pipewire-0` and
`$XDG_RUNTIME_DIR/pulse/native`. Stop older manually launched audio processes
before restarting the desktop; the manager will not kill unrelated servers.

For an older installation, install these packages before upgrading the full
`bme-config` package, then log out of the desktop and back in:

```sh
sudo apt install pipewire pipewire-bin pipewire-pulse pipewire-alsa wireplumber \
  pulseaudio-utils pavucontrol alsa-utils alsa-ucm-conf \
  firmware-sof-signed firmware-intel-sound
```

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

TTY4 shows kernel, boot and system diagnostics, with no login prompt. Use
Ctrl+Alt+F2 or Ctrl+Alt+F3 to log in for repairs, and Ctrl+Alt+F1 to return
to the login/desktop VT. Logs remain in `/var/log/messages`, `/var/log/rc.log`
and the user's audio log. Missing sound cards or firmware must be resolved
before PipeWire can provide a hardware output.
