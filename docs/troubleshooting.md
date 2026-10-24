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
