#!/bin/bash
# Host tooling may use Bash. Target utilities are ash-compatible.
set -Eeuo pipefail
trap 'status=$?; printf "Build failed (%s) at line %s: %s\n" "$status" "$LINENO" "$BASH_COMMAND" >&2' ERR
cd "$(dirname "$0")/.."
source build/inputs.env
VERSION=${VERSION:-0.1.0-dev}
[[ $VERSION =~ ^[a-zA-Z0-9][a-zA-Z0-9.+~-]*$ ]] || { echo 'Invalid version' >&2; exit 1; }
[[ $(id -u) == 0 ]] || { echo 'Run inside the documented privileged build container' >&2; exit 1; }
mkdir -p out/logs work
exec > >(tee out/logs/build.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
mirror="https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/"
printf 'deb [check-valid-until=no] %s sid main non-free-firmware\n' "$mirror" > work/sources.list
printf '%s\n' "Version: $VERSION" "Architecture: $ARCH" "Snapshot: $DEBIAN_SNAPSHOT" "Source: ${SOURCE_COMMIT:-$(git rev-parse HEAD)}" > out/build-metadata.txt
date -u '+Build time: %Y-%m-%dT%H:%M:%SZ' >> out/build-metadata.txt
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' > out/build-tools.tsv
cp work/sources.list out/repositories.list
bash packages/build.sh "$PWD/work/debs" "$VERSION"

bootstrap() {
    local role=$1 root="$PWD/work/$1" include
    [[ ! -e $root ]] || { echo "Refusing reused root: $root" >&2; exit 1; }
    include=$(sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "manifests/$role.txt" | paste -sd,)
    mmdebstrap --mode=root --variant=minbase --architectures="$ARCH" \
      --include="$include" \
      --aptopt='APT::Install-Recommends "false"' \
      --aptopt='APT::Install-Suggests "false"' \
      --setup-hook='mkdir -p "$1/etc/apt/preferences.d"; printf "Package: systemd systemd-sysv sysvinit-core busybox-init dbus-user-session libpam-systemd\nPin: version *\nPin-Priority: -1\n" > "$1/etc/apt/preferences.d/bme-init"' \
      --customize-hook='printf "#!/bin/sh\nexit 101\n" > "$1/usr/sbin/policy-rc.d"; chmod 755 "$1/usr/sbin/policy-rc.d"' \
      sid "$root" work/sources.list
    # Avoid service starts while assembling the root. This is removed before delivery.
    printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
    chmod 755 "$root/usr/sbin/policy-rc.d"
    cp work/debs/*.deb "$root/tmp/"
    chroot "$root" /bin/sh -c 'dpkg -i /tmp/bme-*.deb'
    bash config/configure-root.sh "$root" "$role"
    if [[ $role == installer ]]; then
        install -Dm755 installer/bme-install "$root/usr/sbin/bme-install"
        install -Dm644 installer/lib/install.sh "$root/usr/lib/bme/install.sh"
        printf 'root:bluemess\n' | chroot "$root" chpasswd
    fi
    chroot "$root" dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' > "out/$role-packages.tsv"
    chroot "$root" dpkg --audit | tee "out/logs/$role-dpkg-audit.log"
    [[ ! -s out/logs/$role-dpkg-audit.log ]]
    [[ $(readlink "$root/bin/sh") == dash ]]
    [[ -x $root/usr/sbin/openrc-init && -x $root/bin/bash ]]
    for applet in ash udhcpc syslogd klogd; do chroot "$root" busybox --list | grep -x "$applet" >/dev/null; done
    chroot "$root" busybox ash -c 'test "$(printf "%s" ash)" = ash; set -eu; : "$((1+1))"'
    if chroot "$root" dpkg-query -W -f='${db:Status-Status}\n' systemd 2>/dev/null | grep -x installed >/dev/null; then
        echo 'Unexpected systemd manager installed' >&2; exit 1
    fi
    chroot "$root" update-initramfs -u -k all
    rm -f "$root/usr/sbin/policy-rc.d" "$root"/tmp/*.deb
    : > "$root/etc/machine-id"
    rm -f "$root/var/lib/dbus/machine-id" "$root/var/lib/urandom/random-seed" "$root/var/lib/misc/random-seed" "$root/var/lib/blue-mess/random-seed"
    find "$root/var/log" -type f -exec truncate -s0 {} +
    chroot "$root" apt-get clean
    if [[ $role == target ]]; then
        # Construction stays pinned; installed machines deliberately track Sid.
        rm -f "$root/etc/apt/sources.list.d/"*.sources "$root/etc/apt/sources.list.d/"*.list
        printf 'deb https://deb.debian.org/debian/ sid main non-free-firmware\n' > "$root/etc/apt/sources.list"
    fi
}
bootstrap target
mkdir -p work/iso/bme work/iso/live work/iso/boot/grub
# Payload is a clean installed system, separate from the live root.
tar --numeric-owner --acls --xattrs --zstd -cpf work/iso/bme/rootfs.tar.zst -C work/target .
(cd work/iso/bme && sha256sum rootfs.tar.zst > SHA256SUMS)
bootstrap installer
mksquashfs work/installer work/iso/live/filesystem.squashfs -comp xz -noappend -processors 2
cp -L work/installer/vmlinuz work/iso/live/vmlinuz
cp -L work/installer/initrd.img work/iso/live/initrd.img
cat > work/iso/boot/grub/grub.cfg <<'GRUB'
set timeout=5
set default=0
serial --unit=0 --speed=115200
terminal_input console serial
terminal_output console serial
menuentry 'Blue Mess Edition installer (UEFI amd64)' {
  linux /live/vmlinuz boot=live components quiet init=/sbin/openrc-init console=tty0 console=ttyS0,115200n8
  initrd /live/initrd.img
}
GRUB
iso="blue-mess-edition-$VERSION-amd64.iso"
# grub-mkrescue supplies an EFI El Torito image and hybrid GPT suitable for USB.
grub-mkrescue --modules='part_gpt part_msdos fat iso9660 normal linux search search_fs_file serial' \
  --product-name='Blue Mess Edition' -o "out/$iso" work/iso
(cd out && sha256sum "$iso" > SHA256SUMS)
xorriso -indev "out/$iso" -report_el_torito plain -report_system_area plain > out/logs/iso-layout.log 2>&1
grep -q 'UEFI' out/logs/iso-layout.log
grep -q 'GPT' out/logs/iso-layout.log
python3 - "$VERSION" "$DEBIAN_SNAPSHOT" <<'PY'
import json, os, pathlib, sys
pathlib.Path('out/build-metadata.json').write_text(json.dumps(dict(version=sys.argv[1],snapshot=sys.argv[2],architecture='amd64',source_commit=os.environ.get('SOURCE_COMMIT','unknown'),validated=False),indent=2)+'\n')
PY
printf 'Candidate ISO assembled: %s. VM verification is required.\n' "out/$iso"
