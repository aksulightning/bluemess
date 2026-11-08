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

If the NVIDIA render node is `root:root` with mode `0660`, adding the user to
`render` alone has no effect. Blue Mess's `--resolve-names=never` udev option
prevents Debian's named-group rule from assigning the node to `render`.
For a quick test, if your user belongs to `video`, run
`sudo chgrp video /dev/dri/renderD128` and retry `bluemess-desktop start`. Use
the actual NVIDIA render node from `/dev/dri/by-path/` if its number differs.
The temporary group change is lost when udev recreates the node.

Run these commands as your regular user to fix ownership across reboots.

```sh
getent group render >/dev/null || sudo groupadd --system render
sudo usermod -aG render "$(id -un)"
sudoedit /etc/init.d/udev
```

Change `--resolve-names=never` to `--resolve-names=early`, reboot, then confirm
the render node shows `root render` and `id -nG` includes `render`. A
`bme-config` upgrade can overwrite the local service edit.
[Debian udev manual](https://manpages.debian.org/unstable/udev/systemd-udevd.8.en.html)

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

From an Openbox terminal, run `bluemess-audio-start` as your regular user.
On an older installation, run `sh /path/to/bluemess-audio-start` using the
[launcher from this repository](../packages/bme-config/root/usr/bin/bluemess-audio-start).
Stop any previous manual PipeWire processes before launching it. Keep the
terminal open while you need audio. Open `pavucontrol` in a second terminal
to select and unmute the intended output. Press Ctrl+C in the launcher
terminal to stop the audio processes it started.

The launcher waits for the PipeWire core to answer `pw-cli info 0` before
starting WirePlumber and `pipewire-pulse`. If manual startup reports
`Failed to connect to PipeWire` or `Host is down`, start `pipewire` in the
foreground and check `pw-cli info 0` from a second terminal in the same
desktop session. The default socket is `$XDG_RUNTIME_DIR/pipewire-0`.
RTKit `ServiceUnknown` warnings concern real-time scheduling. A successful
core query confirms the audio server is reachable despite those warnings.
[PipeWire daemon documentation](https://docs.pipewire.org/page_daemon.html)
