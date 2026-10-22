# Shared engine for interactive and unattended installs. No Bash extensions.
# Passwords are read over stdin, never passed as command arguments or logged.

bme_log() { printf '%s\n' "$*"; [ -z "${BME_LOG:-}" ] || printf '%s\n' "$*" >> "$BME_LOG"; }
bme_die() { bme_log "ERROR: $*" >&2; exit 1; }
bme_run() {
    "$@" >> "$BME_LOG" 2>&1 || bme_die "Command failed: $1. See $BME_LOG"
}
bme_usage() {
    cat <<'EOF'
Blue Mess Edition offline installer (amd64 UEFI; entire disk is erased)
Usage: bme-install [--dry-run] [--disk /dev/DEVICE]
       bme-install --unattended --disk /dev/DEVICE \
         --acknowledge ERASE:/dev/DEVICE --hostname HOST --username USER \
         --password-file FILE [--locale en_US.UTF-8] [--keyboard us] \
         [--timezone Etc/UTC]

--dry-run validates and prints a plan without partitioning or mounting targets.
Unattended mode is intended for disposable VM disks. Its password file must be
owned by root, mode 600 or 400, and contain one plaintext line of 8+ characters.
The root account remains password-locked; the new user receives sudo access.
EOF
}
bme_valid_hostname() {
    [ ${#1} -le 63 ] && printf '%s\n' "$1" | LC_ALL=C grep -Eq '^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$'
}
bme_valid_username() {
    [ ${#1} -le 32 ] && printf '%s\n' "$1" | LC_ALL=C grep -Eq '^[a-z][a-z0-9_-]*$' &&
        case "$1" in root|daemon|bin|sys|sync|games|man|lp|mail|news|uucp|proxy|www-data|backup|list|irc|_apt|nobody) return 1;; *) return 0;; esac
}
bme_validate_settings() {
    bme_valid_hostname "$BME_HOSTNAME" || bme_die 'Invalid hostname.'
    bme_valid_username "$BME_USERNAME" || bme_die 'Invalid or reserved username.'
    if getent passwd "$BME_USERNAME" >/dev/null; then bme_die 'Username already belongs to an existing system account.'; fi
    case "$BME_LOCALE" in *[!A-Za-z0-9_.@-]*|'') bme_die 'Invalid locale.';; esac
    # localedef input list is authoritative; no string interpolation into code.
    grep -Fqx "$BME_LOCALE UTF-8" /usr/share/i18n/SUPPORTED || bme_die 'Select a supported UTF-8 locale.'
    case "$BME_KEYBOARD" in *[!A-Za-z0-9_-]*|'') bme_die 'Invalid keyboard layout.';; esac
    [ -f "/usr/share/X11/xkb/symbols/$BME_KEYBOARD" ] || bme_die 'Unknown XKB keyboard layout.'
    case "$BME_TIMEZONE" in /*|*..*|*[!A-Za-z0-9_+/-]*|'') bme_die 'Invalid timezone.';; esac
    [ -f "/usr/share/zoneinfo/$BME_TIMEZONE" ] || bme_die 'Unknown timezone.'
}
bme_disk_is_used() {
    # lsblk expands descendants, including partitions and device-mapper users.
    # Mounted children, swap and holders all reject the entire backing disk.
    for bme_node in $(lsblk -nrpo NAME "$1"); do
        [ -z "$(findmnt -rn -S "$bme_node" -o TARGET)" ] || return 0
        awk 'NR>1 {print $1}' /proc/swaps | grep -Fxq "$bme_node" && return 0
        bme_base=${bme_node##*/}
        for bme_holder in /sys/class/block/"$bme_base"/holders/*; do
            [ ! -e "$bme_holder" ] || return 0
        done
    done
    # A live filesystem can use a loop device backed by a file on the target.
    # findmnt resolves the file's containing mount before checking its ancestry.
    for bme_backing in /sys/class/block/loop*/loop/backing_file; do
        [ -r "$bme_backing" ] || continue
        IFS= read -r bme_file < "$bme_backing" || continue
        case "$bme_file" in /*) ;; *) bme_file=/$bme_file;; esac
        bme_source=$(findmnt -rn -T "$bme_file" -o SOURCE 2>/dev/null || :)
        bme_source=${bme_source%%\[*}
        case "$bme_source" in /dev/*)
            lsblk -snrpo NAME "$bme_source" 2>/dev/null | grep -Fxq "$1" && return 0;;
        esac
    done
    # Explicitly protect the installer-media mount and every backing ancestor.
    bme_source=$(findmnt -rn -T "$BME_MEDIA" -o SOURCE 2>/dev/null || :)
    bme_source=${bme_source%%\[*}
    case "$bme_source" in /dev/*)
        lsblk -snrpo NAME "$bme_source" 2>/dev/null | grep -Fxq "$1" && return 0;;
    esac
    return 1
}
bme_validate_disk() {
    [ -n "$BME_DISK" ] || bme_die 'Select an explicit target disk.'
    case "$BME_DISK" in /dev/*) ;; *) bme_die 'Target must be a /dev/ block-device path.';; esac
    [ -b "$BME_DISK" ] || bme_die 'Target is not a block device.'
    BME_DISK=$(readlink -f "$BME_DISK")
    [ "$(lsblk -dnro TYPE "$BME_DISK")" = disk ] || bme_die 'Target must be a whole physical/virtual disk, not a partition, optical, loop, or mapped device.'
    [ "$(lsblk -dnro RO "$BME_DISK")" = 0 ] || bme_die 'Target is read-only.'
    bme_size=$(lsblk -bdnro SIZE "$BME_DISK")
    [ "$bme_size" -ge 4294967296 ] || bme_die 'Target must be at least 4 GiB.'
    bme_disk_is_used "$BME_DISK" && bme_die 'Target contains mounted filesystems, swap, active holders, or the installation medium.'
    return 0
}
bme_verify_payload() {
    [ -f "$BME_MEDIA/bme/rootfs.tar.zst" ] || bme_die 'Offline payload missing. Mount installation media at /run/bme-media.'
    [ -f "$BME_MEDIA/bme/SHA256SUMS" ] || bme_die 'Payload checksum manifest missing.'
    bme_hash=$(awk '$2 == "rootfs.tar.zst" {print $1}' "$BME_MEDIA/bme/SHA256SUMS")
    [ ${#bme_hash} -eq 64 ] || bme_die 'Payload manifest must contain exactly one rootfs checksum.'
    case "$bme_hash" in *[!0-9a-fA-F]*) bme_die 'Invalid payload checksum.';; esac
    bme_log 'Checking offline payload integrity...'
    (cd "$BME_MEDIA/bme" && printf '%s  rootfs.tar.zst\n' "$bme_hash" | sha256sum -c -) >> "$BME_LOG" 2>&1 || bme_die 'Payload checksum mismatch; no disk changes made.'
}
bme_require_acknowledgement() {
    [ "$BME_ACK" = "ERASE:$BME_DISK" ] || bme_die 'Destructive acknowledgement does not match the selected disk.'
}
bme_preflight() {
    for bme_command in sfdisk udevadm mkfs.fat mkfs.ext4 mount umount mountpoint tar zstd blkid chroot sha256sum sync; do
        command -v "$bme_command" >/dev/null 2>&1 || bme_die "Required installer tool missing: $bme_command"
    done
}
bme_read_password() {
    if [ "$BME_UNATTENDED" = 1 ]; then
        [ -f "$BME_PASSWORD_FILE" ] && [ ! -L "$BME_PASSWORD_FILE" ] || bme_die 'A regular, non-symlink password file is required.'
        [ "$(stat -c %u "$BME_PASSWORD_FILE")" = 0 ] || bme_die 'Password file must be owned by root.'
        case "$(stat -c %a "$BME_PASSWORD_FILE")" in 400|600) ;; *) bme_die 'Password file permissions must be 400 or 600.';; esac
        IFS= read -r BME_PASSWORD < "$BME_PASSWORD_FILE" || [ -n "${BME_PASSWORD:-}" ] || bme_die 'Cannot read password file.'
        [ "$(awk 'END {print NR}' "$BME_PASSWORD_FILE")" -le 1 ] || bme_die 'Password file must contain exactly one line.'
    else
        [ -t 0 ] || bme_die 'Interactive installation requires a terminal.'
        printf 'Password for %s (8+ characters): ' "$BME_USERNAME"
        BME_STTY=$(stty -g)
        stty -echo
        IFS= read -r BME_PASSWORD || bme_die 'Unable to read password.'
        printf '\nRepeat password: '
        IFS= read -r bme_repeat || bme_die 'Unable to read repeated password.'
        stty "$BME_STTY"; BME_STTY=
        printf '\n'
        [ "$BME_PASSWORD" = "$bme_repeat" ] || bme_die 'Passwords differ.'
        unset bme_repeat
    fi
    [ ${#BME_PASSWORD} -ge 8 ] || bme_die 'Password must contain at least eight characters.'
    case "$BME_PASSWORD" in *:*) bme_die 'Password must not contain a colon.';; esac
}
bme_cleanup() {
    bme_status=$?
    trap - EXIT HUP INT TERM
    [ -z "${BME_STTY:-}" ] || stty "$BME_STTY" || :
    unset BME_PASSWORD
    if [ "${BME_MOUNTED:-0}" = 1 ]; then
        # deepest first; do not use a lazy unmount and report unfinished cleanup.
        for bme_mp in dev/pts dev proc sys run boot/efi ''; do
            if mountpoint -q "$BME_TARGET/$bme_mp"; then
                umount "$BME_TARGET/$bme_mp" || { bme_log "WARNING: could not unmount $BME_TARGET/$bme_mp" >&2; bme_status=1; }
            fi
        done
    fi
    [ "$bme_status" -eq 0 ] || bme_log "Installation did not complete. Review ${BME_LOG:-the error above}; do not reboot into this target." >&2
    exit "$bme_status"
}
bme_install_engine() {
    # Validate again immediately before the destructive operation.
    bme_validate_disk
    bme_log "Partitioning $BME_DISK (GPT, 512 MiB EFI System Partition, ext4 root)..."
    bme_run sfdisk --wipe always "$BME_DISK" <<'EOF'
label: gpt
size=512MiB, type=U, name="BME EFI"
type=L, name="BME root"
EOF
    bme_run udevadm settle --timeout=30
    case "$BME_DISK" in *[0-9]) BME_ESP=${BME_DISK}p1; BME_ROOT=${BME_DISK}p2;; *) BME_ESP=${BME_DISK}1; BME_ROOT=${BME_DISK}2;; esac
    [ -b "$BME_ESP" ] && [ -b "$BME_ROOT" ] || bme_die 'New partition devices did not appear.'
    bme_run mkfs.fat -F 32 -n BME_EFI "$BME_ESP"
    bme_run mkfs.ext4 -F -L BME_ROOT "$BME_ROOT"
    mkdir -p "$BME_TARGET"
    bme_run mount "$BME_ROOT" "$BME_TARGET"
    BME_MOUNTED=1
    bme_log 'Extracting clean installed-system payload...'
    bme_run tar --zstd --numeric-owner --xattrs --acls -xpf "$BME_MEDIA/bme/rootfs.tar.zst" -C "$BME_TARGET"
    mkdir -p "$BME_TARGET/boot/efi"
    bme_run mount "$BME_ESP" "$BME_TARGET/boot/efi"
    bme_root_uuid=$(blkid -s UUID -o value "$BME_ROOT")
    bme_efi_uuid=$(blkid -s UUID -o value "$BME_ESP")
    [ -n "$bme_root_uuid" ] && [ -n "$bme_efi_uuid" ] || bme_die 'Cannot read filesystem UUIDs.'
    cat > "$BME_TARGET/etc/fstab" <<EOF
UUID=$bme_root_uuid / ext4 defaults 0 1
UUID=$bme_efi_uuid /boot/efi vfat umask=0077 0 2
EOF
    printf '%s\n' "$BME_HOSTNAME" > "$BME_TARGET/etc/hostname"
    printf '127.0.0.1 localhost\n127.0.1.1 %s\n::1 localhost ip6-localhost ip6-loopback\n' "$BME_HOSTNAME" > "$BME_TARGET/etc/hosts"
    printf '%s UTF-8\n' "$BME_LOCALE" > "$BME_TARGET/etc/locale.gen"
    printf 'LANG=%s\n' "$BME_LOCALE" > "$BME_TARGET/etc/default/locale"
    printf 'XKBMODEL="pc105"\nXKBLAYOUT="%s"\nXKBVARIANT=""\nXKBOPTIONS=""\n' "$BME_KEYBOARD" > "$BME_TARGET/etc/default/keyboard"
    printf '%s\n' "$BME_TIMEZONE" > "$BME_TARGET/etc/timezone"
    ln -sf "/usr/share/zoneinfo/$BME_TIMEZONE" "$BME_TARGET/etc/localtime"
    # Host and image identifiers must never leak into a new installation.
    rm -f "$BME_TARGET/etc/machine-id" "$BME_TARGET/var/lib/dbus/machine-id" "$BME_TARGET/var/lib/urandom/random-seed" "$BME_TARGET/var/lib/misc/random-seed"
    mkdir -p "$BME_TARGET/var/lib/dbus"
    bme_run mount -t proc proc "$BME_TARGET/proc"
    bme_run mount -t sysfs sysfs "$BME_TARGET/sys"
    bme_run mount --bind /dev "$BME_TARGET/dev"
    bme_run mount --bind /dev/pts "$BME_TARGET/dev/pts"
    bme_run mount -t tmpfs -o mode=0755 tmpfs "$BME_TARGET/run"
    bme_run chroot "$BME_TARGET" dbus-uuidgen --ensure=/etc/machine-id
    ln -sf /etc/machine-id "$BME_TARGET/var/lib/dbus/machine-id"
    bme_run chroot "$BME_TARGET" locale-gen
    bme_run chroot "$BME_TARGET" useradd -m -s /usr/bin/ash -G sudo,audio,video,input "$BME_USERNAME"
    bme_run chroot "$BME_TARGET" usermod -s /usr/bin/ash root
    bme_run chroot "$BME_TARGET" passwd -l root
    # printf is a shell builtin; the secret is never visible in process argv.
    printf '%s:%s\n' "$BME_USERNAME" "$BME_PASSWORD" | chroot "$BME_TARGET" chpasswd >> "$BME_LOG" 2>&1 || bme_die 'Password configuration failed.'
    unset BME_PASSWORD
    printf '%%sudo ALL=(ALL:ALL) ALL\n' > "$BME_TARGET/etc/sudoers.d/blue-mess"
    chmod 440 "$BME_TARGET/etc/sudoers.d/blue-mess"
    bme_run chroot "$BME_TARGET" visudo -cf /etc/sudoers
    bme_run chroot "$BME_TARGET" setupcon --save-only
    bme_run chroot "$BME_TARGET" update-initramfs -u -k all
    # Removable fallback path supports USB/firmware with no writable NVRAM.
    bme_run chroot "$BME_TARGET" grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=BlueMess --removable --no-nvram
    bme_run chroot "$BME_TARGET" update-grub
    mkdir -p "$BME_TARGET/var/log/blue-mess"
    cp "$BME_LOG" "$BME_TARGET/var/log/blue-mess/install.log"
    chmod 600 "$BME_TARGET/var/log/blue-mess/install.log"
    bme_run sync
    bme_log 'Installation complete. Exit the installer, shut down, remove the ISO/USB installation medium, and boot the installed disk. Log in as the new user and run startx. Use sudo for administration.'
}
bme_main() {
    BME_DRY_RUN=0 BME_UNATTENDED=0 BME_DISK='' BME_ACK='' BME_PASSWORD_FILE=''
    BME_HOSTNAME=bluemess BME_USERNAME='' BME_LOCALE=en_US.UTF-8 BME_KEYBOARD=us BME_TIMEZONE=Etc/UTC
    BME_MEDIA=${BME_MEDIA:-/run/bme-media}
    BME_TARGET=/mnt/bme-target
    BME_MOUNTED=0 BME_STTY=
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --help|-h) bme_usage; return 0;;
            --dry-run) BME_DRY_RUN=1; shift; continue;;
            --unattended) BME_UNATTENDED=1; shift; continue;;
            --disk|--acknowledge|--hostname|--username|--password-file|--locale|--keyboard|--timezone)
                [ "$#" -ge 2 ] || bme_die "Missing value for $1"
                case "$1" in
                    --disk) BME_DISK=$2;; --acknowledge) BME_ACK=$2;; --hostname) BME_HOSTNAME=$2;;
                    --username) BME_USERNAME=$2;; --password-file) BME_PASSWORD_FILE=$2;; --locale) BME_LOCALE=$2;;
                    --keyboard) BME_KEYBOARD=$2;; --timezone) BME_TIMEZONE=$2;;
                esac; shift 2;;
            *) bme_die "Unknown option: $1";;
        esac
    done
    [ "$(id -u)" = 0 ] || bme_die 'Run bme-install as root.'
    # A unique private log directory prevents symlink following in /tmp.
    bme_log_dir=$(mktemp -d /tmp/bme-install.XXXXXX)
    BME_LOG=$bme_log_dir/install.log
    : > "$BME_LOG"
    trap bme_cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    bme_log 'Blue Mess Edition — offline amd64 UEFI installer'
    bme_log "Log: $BME_LOG"
    bme_log 'WARNING: installation erases the entire selected disk.'
    lsblk -dp -o NAME,SIZE,MODEL,SERIAL,WWN,TRAN,RO,TYPE
    if [ -z "$BME_DISK" ] && [ "$BME_UNATTENDED" = 0 ]; then
        printf 'Target disk (full /dev/ path): '; IFS= read -r BME_DISK
    fi
    bme_validate_disk
    if [ "$BME_UNATTENDED" = 0 ] && [ "$BME_DRY_RUN" = 0 ]; then
        printf 'Hostname [%s]: ' "$BME_HOSTNAME"; IFS= read -r bme_answer; BME_HOSTNAME=${bme_answer:-$BME_HOSTNAME}
        printf 'Username: '; IFS= read -r BME_USERNAME
        printf 'UTF-8 locale [%s]: ' "$BME_LOCALE"; IFS= read -r bme_answer; BME_LOCALE=${bme_answer:-$BME_LOCALE}
        printf 'Keyboard XKB layout [%s]: ' "$BME_KEYBOARD"; IFS= read -r bme_answer; BME_KEYBOARD=${bme_answer:-$BME_KEYBOARD}
        printf 'Timezone [%s]: ' "$BME_TIMEZONE"; IFS= read -r bme_answer; BME_TIMEZONE=${bme_answer:-$BME_TIMEZONE}
    fi
    [ -n "$BME_USERNAME" ] || { [ "$BME_DRY_RUN" = 1 ] && BME_USERNAME=user; } || bme_die 'Username is required.'
    bme_validate_settings
    bme_log "Plan: $BME_DISK → GPT, 512 MiB FAT32 ESP + ext4 root; host=$BME_HOSTNAME user=$BME_USERNAME locale=$BME_LOCALE keyboard=$BME_KEYBOARD timezone=$BME_TIMEZONE"
    if [ "$BME_DRY_RUN" = 1 ]; then bme_log 'Dry run complete: no disk changes made.'; return 0; fi
    [ -d /sys/firmware/efi ] || bme_die 'Boot the installer in UEFI mode.'
    bme_preflight
    bme_verify_payload
    bme_read_password
    if [ "$BME_UNATTENDED" = 0 ]; then
        printf 'Type ERASE:%s to irreversibly erase this disk: ' "$BME_DISK"
        IFS= read -r BME_ACK
    fi
    bme_require_acknowledgement
    bme_install_engine
}
