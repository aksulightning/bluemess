#!/bin/sh
set -eu
# Host-side package creation; no root privileges required.
output=${1:?usage: packages/build.sh OUTPUT VERSION}
version=${2:?version required}
case "$version" in ''|*[!0-9A-Za-z.+:~_-]*) echo 'Invalid package version' >&2; exit 2;; esac
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)
stage=$(mktemp -d "${TMPDIR:-$output}/bme-package.XXXXXX")
trap 'rm -rf "$stage"' EXIT HUP INT TERM
cp -a "$here/bme-config/root/." "$stage/"
mkdir -p "$stage/DEBIAN" "$stage/usr/bin"
ln -s busybox "$stage/usr/bin/ash"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: bme-config
Version: $version
Section: admin
Priority: optional
Architecture: all
Maintainer: Blue Mess Edition contributors <bluemess@users.noreply.github.com>
Depends: openrc, openrc-init, busybox, init-system-helpers, bash, dash, passwd, login, adduser, debianutils, util-linux, mount, sysvinit-utils, e2fsprogs, udev, kmod, systemd-standalone-sysusers, systemd-standalone-tmpfiles, dbus, elogind, libpam-elogind, libpam-runtime, chrony, iproute2
Description: Blue Mess Edition native OpenRC integration and user defaults
 Supplies native boot and daemon ownership, BusyBox ash, minimal desktop
 defaults and explicit APT policy for Debian Sid.
CONTROL
install -m 0755 "$here/bme-config/postinst" "$stage/DEBIAN/postinst"
install -m 0755 "$here/bme-config/prerm" "$stage/DEBIAN/prerm"
printf '/etc/apt/apt.conf.d/90blue-mess\n' > "$stage/DEBIAN/conffiles"
dpkg-deb --root-owner-group --build "$stage" "$output/bme-config_${version}_all.deb"
