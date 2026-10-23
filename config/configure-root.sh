#!/bin/sh
set -eu
root=${1:?usage: config/configure-root.sh ROOT installer|target}
role=${2:?role required}
case "$role" in installer|target) ;; *) echo 'Unknown role' >&2; exit 2;; esac
[ "$root" != / ] && [ -d "$root/etc" ] || { echo 'Refusing to configure host' >&2; exit 2; }
# Build-time configuration only. The packaged postinst owns ongoing integration.
install -m 0644 "$root/usr/share/blue-mess/os-release" "$root/etc/os-release"
printf 'bluemess\n' > "$root/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 bluemess\n::1 localhost ip6-localhost ip6-loopback\n' > "$root/etc/hosts"
cat > "$root/etc/issue" <<'ISSUE'
Blue Mess Edition (Debian Sid) \n \l
Console login, then bluemess-desktop start for the desktop. Super+Enter or Ctrl+Alt+T: terminal.
ISSUE
# The normal Debian package helpers remain installed and functional.
# Activate one native owner for every daemon; remove inherited SysV runlevels.
for level in sysinit boot default shutdown reboot single; do
    mkdir -p "$root/etc/runlevels/$level"
    find "$root/etc/runlevels/$level" -mindepth 1 -maxdepth 1 -type l -delete
 done
for name in bme-root udev; do
    ln -s "/etc/init.d/$name" "$root/etc/runlevels/sysinit/$name"
done
for name in bme-localmount bme-boot; do
    ln -s "/etc/init.d/$name" "$root/etc/runlevels/boot/$name"
done
for name in dbus elogind chrony bme-network bme-syslog bme-klog; do
    ln -s "/etc/init.d/$name" "$root/etc/runlevels/default/$name"
done
ln -s /etc/init.d/bme-mount-ro "$root/etc/runlevels/shutdown/bme-mount-ro"
for port in tty1 tty2 ttyS0; do
    ln -sfn /etc/init.d/bme-getty "$root/etc/init.d/bme-getty.$port"
    ln -s "/etc/init.d/bme-getty.$port" "$root/etc/runlevels/default/bme-getty.$port"
done
cat >> "$root/etc/rc.conf" <<'RC'
# Blue Mess native OpenRC PID 1; individual services have explicit dependencies.
rc_parallel="NO"
rc_logger="YES"
rc_log_path="/var/log/rc.log"
rc_shell="/usr/bin/ash"
RC
# Live media has a transient overlay; target root is checked by initramfs-tools.
if [ "$role" = installer ]; then
    ln -s /etc/init.d/bme-media "$root/etc/runlevels/default/bme-media"
    printf '\nInstaller media: root password is bluemess. Run bme-install.\n' >> "$root/etc/issue"
fi
if [ "$role" = target ]; then
    sed -i 's/^CriticalPowerAction=.*/CriticalPowerAction=PowerOff/' "$root/etc/UPower/UPower.conf"
fi
# /bin/sh and /bin/bash must remain real Debian interpreter choices.
chroot "$root" /bin/sh -c '[ "$(readlink -f /bin/sh)" = /usr/bin/dash ] || [ "$(readlink -f /bin/sh)" = /bin/dash ]'
chroot "$root" /bin/bash -c 'test -n "$BASH_VERSION"'
chroot "$root" /usr/bin/ash -c 'set -- one two; test "$#" -eq 2; test "${1}" = one'
chroot "$root" /usr/bin/ash -c '[ "$(getent passwd root | cut -d: -f7)" = /usr/bin/ash ]'
# Never ship build-host entropy or machine identifiers.
rm -f "$root/etc/machine-id" "$root/var/lib/dbus/machine-id" "$root/var/lib/blue-mess/random-seed"
touch "$root/etc/machine-id"
