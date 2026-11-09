# Architecture and integration

Blue Mess Edition uses Debian Sid amd64 packages with native `openrc-init` as PID 1. There is no init metapackage, display manager, systemd manager, SysVinit PID 1, or BusyBox init. Debian `bash`, `dash`, `init-system-helpers`, udev and their original interpreters remain present. `/bin/sh` remains dash. The package-owned `/usr/bin/ash` symlink selects Debian BusyBox ash; root and installed user login shells use it. Blue Mess utilities use POSIX shell syntax supported by ash: no arrays, process substitution, Bash conditional expressions or `pipefail` assumption.

## Debian integration checked during implementation

Sid source metadata inspected: OpenRC `0.64.1-2`, `debian/control`, `debian/rules`, `debian/openrc.install`, `debian/openrc-init.install` and `debian/src/init.d`. `openrc-init` depends on `openrc`, conflicts with alternate init providers, and provides `/sbin/init` as a link to native `openrc-init`. Debian's OpenRC packaging removes upstream Gentoo boot services and runlevel links, so installing OpenRC alone is insufficient. Debian provides agetty, cgroups, rc, rcS, savecache and user entry points; Blue Mess supplies the missing boot and daemon services.

Debian BusyBox `1:1.38.0-3` configuration was inspected. Ash, job control, getopts, udhcpc, syslogd and klogd are enabled. ntpd is disabled, so time synchronization uses explicitly installed chrony. The configuration package also asserts required applets during installation. Neither source inspection nor package creation establishes successful VM boot; consult the verification report for run results.

Sources:

- https://sources.debian.org/src/openrc/0.64.1-2/debian/
- https://sources.debian.org/src/busybox/1%3A1.38.0-3/debian/config/pkg/deb/

## Native boot sequence

| Runlevel | Services | Purpose |
| --- | --- | --- |
| sysinit | bme-root, udev | Writable root and kernel filesystems; device discovery and coldplug |
| boot | bme-localmount, bme-boot | Non-root fsck, fstab mounts, hostname, modules, sysctls, UTC hardware clock, random seed, machine identifiers, console and ALSA restore |
| default | dbus, elogind | System bus, ordinary-user PAM login, seats and device access |
| default | bme-network, chrony | One configured DHCP connection, DNS and time synchronization |
| default | bme-syslog, bme-klog | Rotating system log and kernel messages |
| default | greetd | Installed-system tty1 login through tuigreet and Debian PAM |
| default | bme-getty.tty1, bme-getty.tty2, bme-getty.tty3, bme-getty.ttyS0 | agetty on tty2, tty3 and serial, plus tty1 on the live installer |
| default, media only | bme-media | Locate the separate clean installed-system payload |
| shutdown | bme-mount-ro | Final read-only root remount after OpenRC closes its log |

initramfs-tools owns root filesystem checks before mounting root. `bme-localmount` checks remaining local filesystems and mounts fstab entries. Dependency ordering stops application daemons and gettys before local unmounting, then the shutdown runlevel restores a read-only root after OpenRC closes its writable log. `killall5` from `sysvinit-utils` handles remaining user processes while excluding PID 1 and the shutdown session; it does not provide an alternate PID 1. Native OpenRC sends final TERM/KILL, syncs and performs reboot/poweroff.

The configuration package diverts Debian's dbus, elogind, chrony, udev and installed-system greetd service entry points to preserved vendor paths and installs native `openrc-run` entry points. Package maintainer `invoke-rc.d` and service actions use these entry points. Removal restores diverted scripts. Debian LSB metadata lives in `/etc/insserv/overrides/`, separate from native service code. Debian OpenRC classifies inline `INIT INFO` headers as LSB scripts and bypasses native service command definitions, so these headers must never be added to the native wrappers. Image construction asserts native classification using Debian's actual `lsb2rcconf` tool and verifies unmodified `dpkg`/`init-system-helpers` package files. Build-time policy preventing daemon starts is limited to image construction. The configuration step removes inherited runlevel links and activates exactly one owner per daemon.

The explicitly installed `systemd-standalone-sysusers` and `systemd-standalone-tmpfiles` helpers run during `bme-boot` to apply the user definitions and runtime-directory rules present on the system. See [the X11 socket ownership fix](troubleshooting.md#x11-socket-ownership) if the X11 tmpfiles rule is missing. These standalone commands run under OpenRC.

The kernel udev daemon may have `systemd` in its filename. That is permitted: it is a device helper rather than a system or user service manager. Runtime verification must assert `/proc/1/exe`, service state and actual processes.

## Networking, firmware and audio

`bme-network` selects the first physical wired interface by default and runs one BusyBox udhcpc client. The DHCP callback configures its IPv4 address, default route and `/etc/resolv.conf`. The resolver file belongs to this connection and no competing resolver daemon is enabled. With no suitable device the service waits without repeatedly spawning failed clients. DHCP remains active for lease renewal. NetworkManager, ifupdown and a second DHCP client are unnecessary.

For Wi-Fi, create `/etc/blue-mess/network.conf` with `mode=wifi` and `interface=wlan0` (use the actual name from `ip link`). Create a mode-0600 `/etc/wpa_supplicant/bme.conf` with a `network={...}` block produced by `wpa_passphrase`, removing its commented plaintext password line. Restart `bme-network` with `rc-service bme-network restart`. Only Wi-Fi mode starts wpa_supplicant. `iw` supplies diagnostics. Intel and Realtek firmware are selected explicitly; hardware outside the included firmware coverage may need additional Sid firmware. Only one connection is managed in this first version.

ALSA uses kernel sound drivers, UCM profiles and packaged Intel/SOF firmware. `alsactl` restores saved mixer levels, initializes defaults when no saved state is usable, and saves levels at shutdown. The desktop launches one `bluemess-audio run` supervisor on its session D-Bus. It starts PipeWire, waits for the core, then starts WirePlumber and pipewire-pulse. A per-user runtime lock prevents duplicates, process failures trigger at most three recovery attempts, and desktop logout cleans up the stack. No root audio daemon or systemd user manager is required. ALSA and PulseAudio applications connect through the PipeWire compatibility packages. Output selection and volume remain user preferences. chrony performs normal network synchronization and retains its own drift state. BusyBox syslogd rotates `/var/log/messages` at 256 KiB with two backups. OpenRC keeps `/var/log/rc.log`. Both boot paths select `console=tty4` as the final console argument, so kernel/init output stays on tty4 after switching to tty1. BusyBox syslog additionally mirrors userspace messages to tty4; kernel messages are already there. TTY4 has no getty. Only tty1, tty2 and tty3 provide numbered login consoles. The serial recovery console is separate from the F-key layout.

## Session and desktop

On installed systems, greetd starts tuigreet on tty1 and authenticates through Debian's PAM stack with `libpam-elogind`. Elogind provides seat and device access for rootless Xorg. Tuigreet opens the user's interactive ash login shell after password authentication. `bluemess-desktop start` launches the packaged session from that shell, and `startx` uses the new-account `.xinitrc` wrapper. `bluemess-desktop auto-start true|false` stores a per-user flag under `${XDG_CONFIG_HOME:-$HOME/.config}/blue-mess/auto-start`. A guarded hook at the end of the user profile checks that flag, the user ID, tty1 and the absence of an existing graphical display. Enabling auto-start appends the hook once so user PATH and XDG settings are available first. Default is false. When X exits, the hook returns to the authenticated shell. Exiting that shell returns to tuigreet.

The session helper starts a private `dbus-run-session`, then Openbox, one `xfce4-panel`, `xfce4-power-manager` and `lxpolkit`. It seeds missing XFCE configuration files for existing users without overwriting their settings, and terminates its companion processes when Openbox exits. UPower and polkit use their packaged system D-Bus activation entry points under native OpenRC; no systemd manager or XFCE session manager is installed. The bottom panel contains a terminal launcher, task list, workspace switcher, notification area, power plugin and clock. Terminals open on demand.

Default power configuration disables idle suspend, dimming, display blanking/DPMS and screen locking. No screensaver is installed. elogind owns lid-close suspend; UPower uses PowerOff for critical battery action, and the power manager uses the same shutdown policy. Actual laptop battery/lid behavior requires hardware validation. Users may change their own power settings later.

The installed target explicitly includes `build-essential`, `linux-headers-amd64`, `dkms` and `lua5.4`. The image and headers are resolved from the same signed snapshot, and the VM compiles a small C program and a harmless external kernel module without loading it. Python is retained because the snapshot's Debian `openbox` package has a direct `python3` dependency. Project desktop/session utilities use ash, not Python.

Drag the titlebar to move a window, or hold Alt and drag with the left mouse button anywhere on it. Drag an edge/corner to resize, or use Alt with the right mouse button. Alt+F7 starts keyboard movement and Alt+F8 starts keyboard resizing; use the arrow keys and Enter to finish (Escape cancels). Double-click the titlebar or click its maximize button to toggle maximization.

Super+Enter or Ctrl+Alt+T starts a terminal; Alt+Tab switches windows, Alt+F4 closes one, Super+Space opens the application menu, and right-clicking the root background also opens it. Super+Left/Right changes workspace. Home creation copies hidden configuration and creates only the visible `Documents` and `Downloads` directories. Other XDG directory variables point to `$HOME`, and automatic user-directory updates are disabled.

The target package manifest is separate from the installer environment. The installer extracts a clean payload rather than cloning live overlay state. The package owns configuration assets, its ash entry point and service sources; the image configuration stage installs boot-role-specific runlevel links and branding. Update Debian Sid through its signed repositories with Recommends/Suggests disabled; inspect proposed upgrades before accepting init/service or graphics changes. Sid is a rolling development distribution and can break. The build's immutable snapshot records resolved inputs; refreshing it requires a complete new installation and memory verification run.
