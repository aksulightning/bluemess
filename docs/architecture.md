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
| default | bme-getty.tty1, bme-getty.tty2, bme-getty.ttyS0 | Authenticated console login, supervised by OpenRC |
| default, media only | bme-media | Locate the separate clean installed-system payload |
| shutdown | bme-mount-ro | Final read-only root remount after OpenRC closes its log |

initramfs-tools owns root filesystem checks before mounting root. `bme-localmount` checks remaining local filesystems and mounts fstab entries. Dependency ordering stops application daemons and gettys before local unmounting, then the shutdown runlevel restores a read-only root after OpenRC closes its writable log. `killall5` from `sysvinit-utils` handles remaining user processes while excluding PID 1 and the shutdown session; it does not provide an alternate PID 1. Native OpenRC sends final TERM/KILL, syncs and performs reboot/poweroff.

The configuration package diverts Debian's dbus, elogind, chrony and udev service entry points to preserved vendor paths and installs proper `openrc-run` entry points. Thus package maintainer `invoke-rc.d`/service actions have a real service implementation; they are not replaced with unconditional-success commands. Removal restores diverted scripts. Debian LSB metadata lives in `/etc/insserv/overrides/`, separate from native service code. Debian OpenRC classifies inline `INIT INFO` headers as LSB scripts and bypasses native service command definitions, so these headers must never be added to the native wrappers. Image construction asserts native classification using Debian's actual `lsb2rcconf` tool and verifies unmodified `dpkg`/`init-system-helpers` package files. Build-time policy preventing daemon starts is limited to image construction. The configuration step removes inherited runlevel links and activates exactly one owner per daemon.

The explicitly installed `systemd-standalone-sysusers` and `systemd-standalone-tmpfiles` helpers run during `bme-boot` to apply Debian package user definitions and runtime directories, including the root-owned sticky X11/ICE socket directories required by rootless Xorg. They are standalone command-line helpers and do not start a systemd manager.

The kernel udev daemon may have `systemd` in its filename. That is permitted: it is a device helper rather than a system or user service manager. Runtime verification must assert `/proc/1/exe`, service state and actual processes.

## Networking, firmware and audio

`bme-network` selects the first physical wired interface by default and runs one BusyBox udhcpc client. The DHCP callback configures its IPv4 address, default route and `/etc/resolv.conf`. The resolver file belongs to this connection and no competing resolver daemon is enabled. With no suitable device the service waits without repeatedly spawning failed clients. DHCP remains active for lease renewal. NetworkManager, ifupdown and a second DHCP client are unnecessary.

For Wi-Fi, create `/etc/blue-mess/network.conf` with `mode=wifi` and `interface=wlan0` (use the actual name from `ip link`). Create a mode-0600 `/etc/wpa_supplicant/bme.conf` with a `network={...}` block produced by `wpa_passphrase`, removing its commented plaintext password line. Restart `bme-network` with `rc-service bme-network restart`. Only Wi-Fi mode starts wpa_supplicant. `iw` supplies diagnostics. Intel and Realtek firmware are selected explicitly; hardware outside the included firmware coverage may need additional Sid firmware. Only one connection is managed in this first version.

ALSA uses kernel sound drivers and `alsa-utils`; `alsamixer` is available on demand and `alsactl` saves/restores mixer state. No PulseAudio or PipeWire daemon is enabled. chrony performs normal network synchronization and retains its own drift state. BusyBox syslogd rotates `/var/log/messages` at 256 KiB with two backups; OpenRC keeps `/var/log/rc.log`.

## Session and desktop

Console login uses normal PAM with explicit `libpam-elogind`. elogind provides seat/device access for rootless Xorg. Run `startx` from the ordinary user's tty1 session. `.xinitrc` sets the blue background, starts one idle xterm using ash, and executes `dbus-run-session -- openbox`. Plain `openbox` deliberately bypasses `openbox-session` and its XDG autostart processing. No compositor, panel, display manager, indexing service or update helper starts. Fastfetch and htop run only on demand.

Super+Enter or Ctrl+Alt+T starts a terminal; Alt+Tab switches windows, Alt+F4 closes one, Super+Space opens the application menu, and right-clicking the root background also opens it. Super+Left/Right changes workspace. Home creation copies hidden configuration and creates only the visible `Documents` and `Downloads` directories. Other XDG directory variables point to `$HOME`, and automatic user-directory updates are disabled.

The target package manifest is separate from the installer environment. The installer extracts a clean payload rather than cloning live overlay state. The package owns configuration assets, its ash entry point and service sources; the image configuration stage installs boot-role-specific runlevel links and branding. Update Debian Sid through its signed repositories with Recommends/Suggests disabled; inspect proposed upgrades before accepting init/service or graphics changes. Sid is a rolling development distribution and can break. The build's immutable snapshot records resolved inputs; refreshing it requires a complete new installation and memory verification run.
