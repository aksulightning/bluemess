#!/usr/bin/env python3
"""Real UEFI/TCG install, authenticated console/desktop and memory acceptance.

Only disposable qcow2 files created by this program are attached as hard disks.
No guest-side verification hook, fixture media or CI credential enters the ISO.
"""
import argparse
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import secrets
import select
import shlex
import shutil
import socket
import subprocess
import sys
import time
import traceback

from benchmark import parse_meminfo, summarize

CONFIG = {'architecture': 'amd64', 'ram_MiB': 1024, 'vcpus': 2,
          'machine': 'pc-q35-8.2', 'cpu': 'qemu64', 'acceleration': 'tcg',
          'graphics': 'std VGA', 'resolution': '1024x768',
          'settle_seconds': 60, 'fresh_boots': 3, 'swap_used_kib': 0,
          'metric': '(MemTotal_kib - MemAvailable_kib) / 1024',
          'threshold_MiB': 150}


class Failure(RuntimeError):
    pass


class QMP:
    def __init__(self, path, process):
        deadline = time.monotonic() + 30
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        while True:
            try:
                self.sock.connect(str(path))
                break
            except (ConnectionRefusedError, FileNotFoundError):
                if process.poll() is not None or time.monotonic() > deadline:
                    raise Failure('QEMU did not create its QMP socket')
                time.sleep(.1)
        self.sock.settimeout(30)
        self.stream = self.sock.makefile('rwb', buffering=0)
        self.events = []
        if 'QMP' not in self._read():
            raise Failure('No QMP greeting')
        self.command('qmp_capabilities')

    def _read(self):
        line = self.stream.readline()
        if not line:
            raise Failure('QMP disconnected unexpectedly')
        return json.loads(line)

    def command(self, command, arguments=None):
        request = {'execute': command}
        if arguments:
            request['arguments'] = arguments
        self.stream.write(json.dumps(request).encode() + b'\n')
        while True:
            result = self._read()
            if 'event' in result:
                self.events.append(result)
            elif 'error' in result:
                raise Failure(f'QMP {command}: {result["error"]}')
            elif 'return' in result:
                return result['return']

    def type(self, text):
        punctuation = {' ': 'spc', '\n': 'ret', '-': 'minus', '.': 'dot', '/': 'slash'}
        for char in text:
            code = punctuation.get(char, char)
            if not (char.isascii() and (char.islower() or char.isdigit() or char in punctuation)):
                raise Failure('Unsupported QMP keyboard input')
            self.command('send-key', {'keys': [{'type': 'qcode', 'data': code}], 'hold-time': 30})
            time.sleep(.05)

    def close(self):
        self.stream.close()
        self.sock.close()


class Guest:
    def __init__(self, args, work, phase, disk, variables, network, iso=None, usb_media=False):
        self.buffer = ''
        self.redactions = []
        self.log = (work.parent / f'{phase}-serial.log').open('w', encoding='utf-8')
        qmp_path = work / f'{phase}.qmp'
        qmp_path.unlink(missing_ok=True)
        command = ['qemu-system-x86_64', '-machine', CONFIG['machine'] + ',accel=tcg',
                   '-cpu', CONFIG['cpu'], '-smp', str(CONFIG['vcpus']), '-m', '1024',
                   '-vga', 'std', '-display', 'none', '-monitor', 'none', '-serial', 'stdio',
                   '-qmp', f'unix:{qmp_path},server=on,wait=off',
                   '-drive', f'if=pflash,format=raw,readonly=on,file={args.ovmf_code}',
                   '-drive', f'if=pflash,format=raw,file={variables}',
                   '-drive', f'if=virtio,format=qcow2,file={disk}',
                   '-boot', 'order=d' if iso else 'order=c']
        command += ['-nic', 'user,model=virtio-net-pci'] if network else ['-nic', 'none']
        if iso and usb_media:
            command += ['-device', 'qemu-xhci',
                        '-drive', f'if=none,id=installmedia,file={iso},format=raw,readonly=on',
                        '-device', 'usb-storage,drive=installmedia,bootindex=1']
        elif iso:
            command += ['-drive', f'file={iso},format=raw,media=cdrom,readonly=on']
        (work.parent / f'{phase}-qemu.json').write_text(json.dumps(command, indent=2) + '\n')
        master, slave = pty.openpty()
        self.fd = master
        self.process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        self.qmp = QMP(qmp_path, self.process)

    def safe(self, text):
        for secret in self.redactions:
            text = text.replace(secret, '[REDACTED]')
        return text

    def send(self, text):
        os.write(self.fd, text.encode())

    def until(self, pattern, timeout=120):
        regex = re.compile(pattern, re.DOTALL)
        deadline = time.monotonic() + timeout
        while True:
            match = regex.search(self.buffer)
            if match:
                before = self.buffer[:match.start()]
                self.buffer = self.buffer[match.end():]
                return before, match
            if time.monotonic() > deadline:
                raise Failure(f'Timeout waiting for {pattern!r}; tail: {self.safe(self.buffer[-2000:])}')
            ready, _, _ = select.select([self.fd], [], [], min(1, max(0, deadline - time.monotonic())))
            if ready:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    data = b''
                if not data:
                    raise Failure(f'QEMU serial closed, exit={self.process.poll()}; tail: {self.safe(self.buffer[-2000:])}')
                text = data.decode('utf-8', errors='replace').replace('\r', '')
                self.log.write(self.safe(text))
                self.log.flush()
                self.buffer += text

    def login(self, user, password):
        _, boot_match = self.until(r'(?:^|\n)[^\n]*login:\s*|Kernel panic[^\n]*|ERROR: (?:bme-boot failed to start|cannot start bme-getty[^\n]*)', 900)
        if 'login:' not in boot_match.group(0):
            raise Failure('Guest boot failed before console login: ' + boot_match.group(0))
        self.send(user + '\n')
        self.until(r'Password:\s*', 60)
        self.send(password + '\n')
        self.until(r'(?:^|\n)[^\n]*[#$] ', 120)
        # Prompt is intentionally not assumed. A command marker proves a shell.
        self.send('stty -echo\n')
        output = self.run('id -un; printf "%s\\n" "$SHELL"; readlink /proc/$$/exe')
        if user not in output.splitlines() or '/usr/bin/ash' not in output or 'busybox' not in output:
            raise Failure('Authenticated login did not enter BusyBox ash: ' + output)

    def root(self, password):
        marker = 'BME_SUDO_' + secrets.token_hex(8)
        self.send(f"sudo -S -p '{marker}:' /usr/bin/ash\n")
        self.until(re.escape(marker) + ':', 60)
        self.send(password + '\n')
        self.until(r'(?:^|\n)[^\n]*[#$] ', 120)
        if self.run('id -u').strip() != '0':
            raise Failure('Password-authenticated sudo did not produce root')

    def run(self, command, timeout=120, check=True):
        nonce = secrets.token_hex(12)
        begin, end = 'BME_BEGIN_' + nonce, 'BME_END_' + nonce
        # Split markers prevent a terminal echo of the command from satisfying assertions.
        wrapped = f"printf '\\nBME_''BEGIN_{nonce}\\n'; ( {command}\n); bme_rc=$?; printf '\\nBME_''END_{nonce}:%s\\n' \"$bme_rc\"\n"
        self.send(wrapped)
        self.until(re.escape(begin) + '\n', timeout)
        output, match = self.until(re.escape(end) + r':([0-9]+)\n', timeout)
        if check and int(match.group(1)) != 0:
            raise Failure(f'Guest command failed ({match.group(1)}): {self.safe(command)}\n{self.safe(output[-4000:])}')
        return output.strip('\n')

    def reboot(self):
        self.send('sync; openrc-shutdown --reboot now\n')
        # Next login() waits for a new real getty after the kernel boots again.

    def poweroff(self):
        self.send('sync; openrc-shutdown --poweroff now\n')
        deadline = time.monotonic() + 180
        while self.process.poll() is None and time.monotonic() < deadline:
            if select.select([self.fd], [], [], .5)[0]:
                with suppress(OSError):
                    data = os.read(self.fd, 65536)
                    self.log.write(data.decode(errors='replace').replace('\r', ''))
                    self.log.flush()
        if self.process.poll() != 0:
            raise Failure('Guest did not power off cleanly within 180 seconds')

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(15)
        self.qmp.close()
        os.close(self.fd)
        self.log.close()


def record(output, name, text):
    (output / name).write_text(text + '\n')
    return text


def root_state(guest, output, suffix):
    facts = guest.run('''set -eu
readlink /proc/1/exe
case "$(readlink /proc/1/exe)" in */openrc-init) ;; *) exit 1;; esac
rc-status --all
for service in bme-root udev bme-localmount bme-boot bme-network bme-syslog bme-klog dbus elogind chrony bme-getty.tty1 bme-getty.tty2 bme-getty.ttyS0; do rc-service "$service" status; done
findmnt -n -o FSTYPE /
test "$(findmnt -n -o FSTYPE /)" = ext4
test "$(findmnt -n -o FSTYPE /boot/efi)" = vfat
findmnt -n -o SOURCE,UUID,FSTYPE /; findmnt -n -o SOURCE,UUID,FSTYPE /boot/efi
awk '$2 == "/" || $2 == "/boot/efi" {if ($1 !~ /^UUID=/) exit 1; n++} END {if (n != 2) exit 1}' /etc/fstab
test "$(readlink -f /bin/sh)" = /usr/bin/dash
case "$(readlink -f /bin/bash)" in */bash) ;; *) exit 1;; esac
test "$(getent passwd root | cut -d: -f7)" = /usr/bin/ash
test "$(getent passwd tester | cut -d: -f7)" = /usr/bin/ash
useradd -D | grep -x 'SHELL=/usr/bin/ash'
grep -x 'DSHELL=/usr/bin/ash' /etc/adduser.conf
getent shells 2>/dev/null || cat /etc/shells
! pgrep -x systemd
! pgrep -x systemd-init
''')
    record(output, f'system-{suffix}.log', facts)
    return facts


def network(guest, output, suffix):
    facts = guest.run('''set -eu
n=0; until ip -4 route show default | grep -q default; do n=$((n+1)); test "$n" -le 90; sleep 1; done
ip -details address
ip route
cat /etc/resolv.conf
getent ahostsv4 deb.debian.org
''', timeout=180)
    record(output, f'network-{suffix}.log', facts)


def desktop(guest, password, output, suffix):
    guest.run('chvt 1')
    guest.qmp.type('tester\n')
    time.sleep(3)
    guest.qmp.type(password + '\n')
    time.sleep(3)
    guest.run('''n=0; until who | grep -q 'tester.*tty1'; do n=$((n+1)); test "$n" -le 90 || exit 1; sleep 1; done''', timeout=120)
    guest.qmp.type('startx\n')
    guest.run('''n=0; until pgrep -u tester -x openbox >/dev/null; do n=$((n+1)); test "$n" -le 180 || { cat /home/tester/.local/share/xorg/Xorg.0.log; exit 1; }; sleep 1; done''', timeout=240)
    # Select the same resolution on the real guest VGA server on every boot.
    guest.run('runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority xrandr -s 1024x768')
    if not guest.run('pgrep -u tester -x xterm || true').strip():
        guest.qmp.command('send-key', {'keys': [{'type': 'qcode', 'data': 'ctrl'}, {'type': 'qcode', 'data': 'alt'}, {'type': 'qcode', 'data': 't'}], 'hold-time': 100})
    facts = guest.run('''set -eu
n=0; until pgrep -u tester -x xterm >/dev/null; do n=$((n+1)); test "$n" -le 90; sleep 1; done
test "$(pgrep -u tester -x xterm | wc -l)" -eq 1
xpid=$(pgrep -u tester -x Xorg); test -n "$xpid"
obpid=$(pgrep -u tester -x openbox); test -n "$obpid"
tpid=$(pgrep -u tester -x xterm); test -n "$tpid"
child=$(ps -o pid= --ppid "$tpid" | head -n 1 | tr -d ' '); test -n "$child"
case "$(readlink /proc/"$child"/exe)" in */busybox) ;; *) exit 1;; esac
tr '\\000' ' ' < /proc/"$child"/cmdline | grep -Eq '(^|/|-| )ash( |$)'
tr '\\000' ' ' < /proc/"$child"/cmdline; printf '\\n'
ps -eo pid,ppid,user,tty,args
runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority xrandr --current
runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority xprop -root _NET_SUPPORTING_WM_CHECK
loginctl list-sessions
cat /home/tester/.local/share/xorg/Xorg.0.log
''', timeout=180)
    record(output, f'desktop-{suffix}.log', facts)
    guest.qmp.command('screendump', {'filename': str(output / f'desktop-{suffix}.ppm')})


def memory(guest, output, boot):
    # The only activity during settling is QEMU's ordinary delivered guest services.
    time.sleep(CONFIG['settle_seconds'])
    reading = record(output, f'meminfo-boot-{boot}.txt', guest.run('cat /proc/meminfo'))
    result = parse_meminfo(reading)
    record(output, f'memory-diagnostics-boot-{boot}.log', guest.run('''printf '%s\\n' '--- services ---'; rc-status --all
printf '%s\\n' '--- processes ---'; ps -eo pid,ppid,user,rss,vsz,args --sort=-rss
printf '%s\\n' '--- kernel slab totals ---'; head -n 30 /proc/slabinfo
printf '%s\\n' '--- per-process PSS KiB ---'
for p in /proc/[0-9]*; do
 test -r "$p/smaps_rollup" || continue
 name=$(cat "$p/comm" 2>/dev/null) || continue
 awk -v pid="${p##*/}" -v name="$name" '$1 == "Pss:" {print pid, $2, name}' "$p/smaps_rollup" 2>/dev/null || :
done
'''))
    return result


def defaults():
    for base in (Path('/usr/share/OVMF'), Path('/usr/share/edk2/ovmf')):
        for code, variables in (('OVMF_CODE_4M.fd', 'OVMF_VARS_4M.fd'), ('OVMF_CODE.fd', 'OVMF_VARS.fd')):
            if (base / code).is_file() and (base / variables).is_file():
                return str(base / code), str(base / variables)
    return '/usr/share/OVMF/OVMF_CODE_4M.fd', '/usr/share/OVMF/OVMF_VARS_4M.fd'


def main():
    code, variables = defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('out/verification'))
    parser.add_argument('--ovmf-code', default=code)
    parser.add_argument('--ovmf-vars', default=variables)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result = {'status': 'failed', 'configuration': CONFIG, 'checks': [], 'memory': None}
    guest = None
    try:
        iso = args.iso.resolve(strict=True)
        if ',' in str(iso) or ',' in str(output):
            raise Failure('QEMU artifact paths must not contain commas')
        work = output / 'work'
        # Never reuse an installation from another test run.
        work.mkdir(exist_ok=False)
        disk = work / 'installed.qcow2'
        nvram = work / 'OVMF_VARS.fd'
        shutil.copyfile(args.ovmf_vars, nvram)
        result['iso'] = iso.name
        with iso.open('rb') as stream:
            result['iso_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        result['qemu_version'] = subprocess.check_output(['qemu-system-x86_64', '--version'], text=True).strip()
        subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(disk), '12G'], check=True)
        password = secrets.token_hex(16)
        # Exercise the exact ISO bytes as USB mass-storage before optical install.
        # The only hard disk remains our newly created disposable /dev/vda.
        guest = Guest(args, work, 'usb-installer', disk, nvram, network=False, iso=iso, usb_media=True)
        guest.redactions = [password]
        guest.login('root', 'bluemess')
        usb_facts = guest.run('''set -eu
case "$(readlink /proc/1/exe)" in */openrc-init) ;; *) exit 1;; esac
test -d /sys/firmware/efi
test "$(ls /sys/class/net | wc -l)" -eq 1
test -d /sys/class/net/lo
test -f /run/bme-media/bme/rootfs.tar.zst
test -f /run/bme-media/bme/SHA256SUMS
media_path=$(readlink -f /run/bme-media)
media_source=$(findmnt -rn -T "$media_path" -o SOURCE)
media_source=${media_source%%\\[*}
media_disk=$(lsblk -snrpo NAME,TYPE,TRAN "$media_source" | awk '$2 == "disk" && $3 == "usb" {print $1; exit}')
test -n "$media_disk"
test "$media_disk" != /dev/vda
printf 'USB boot medium: %s (mount source %s)\\n' "$media_disk" "$media_source"
findmnt -rn -T "$media_path" -o SOURCE,TARGET,FSTYPE,OPTIONS
lsblk -o NAME,TYPE,SIZE,TRAN,RO,FSTYPE
before=$(dd if=/dev/vda bs=4096 count=1 status=none | sha256sum)
if bme-install --dry-run --disk "$media_disk" > /run/bme-usb-rejection.log 2>&1; then
    cat /run/bme-usb-rejection.log
    printf '%s\\n' 'ERROR: installer accepted its own USB boot medium'
    exit 1
fi
cat /run/bme-usb-rejection.log
grep -Eq 'ERROR: Target (is read-only|must be at least 4 GiB|contains mounted filesystems, swap, active holders, or the installation medium)' /run/bme-usb-rejection.log
after=$(dd if=/dev/vda bs=4096 count=1 status=none | sha256sum)
test "$before" = "$after"
test "$(lsblk -nrpo TYPE /dev/vda | wc -l)" -eq 1
''', timeout=180)
        record(output, 'usb-boot-and-media-rejection.log', usb_facts)
        guest.qmp.command('screendump', {'filename': str(output / 'usb-console.ppm')})
        guest.poweroff()
        guest.close()
        guest = None
        result['checks'].append('Identical ISO boots as USB mass-storage with native OpenRC, offline payload mounted, and installer dry-run rejects its own USB disk')
        guest = Guest(args, work, 'installer', disk, nvram, network=False, iso=iso)
        guest.redactions = [password]
        guest.login('root', 'bluemess')
        root_state_live = guest.run('readlink /proc/1/exe; command -v bme-install; test -d /sys/firmware/efi; test "$(ls /sys/class/net | wc -l)" -eq 1; test -d /sys/class/net/lo')
        if '/openrc-init' not in root_state_live:
            raise Failure('Installer PID 1 is not native openrc-init')
        record(output, 'installer-meminfo.txt', guest.run('cat /proc/meminfo'))
        result['checks'].append('ISO reaches native OpenRC CLI; no guest NIC during installation')
        # Terminal echo is disabled and only received output is logged.
        guest.run(f"umask 077; printf '%s\\n' {shlex.quote(password)} > /run/bme-test-password")
        install = guest.run('bme-install --unattended --disk /dev/vda --acknowledge ERASE:/dev/vda --hostname bme-test --username tester --password-file /run/bme-test-password --locale en_US.UTF-8 --keyboard us --timezone Etc/UTC', timeout=1800, check=False)
        record(output, 'installer.log', install)
        record(output, 'installer-engine.log', guest.run('for path in /tmp/bme-install.*/install.log; do test ! -f "$path" || cat "$path"; done', check=False))
        if 'Installation complete.' not in install:
            raise Failure('Installer did not report successful completion')
        record(output, 'installed-partitions.log', guest.run('lsblk -o NAME,TYPE,FSTYPE,PARTTYPE,UUID /dev/vda; blkid /dev/vda1 /dev/vda2'))
        guest.poweroff()
        guest.close()
        guest = None
        result['checks'].append('Actual installer completes offline on disposable GPT/EFI/ext4 disk')
        guest = Guest(args, work, 'installed', disk, nvram, network=True)
        guest.redactions = [password]
        guest.login('tester', password)
        layout = guest.run('find "$HOME" -mindepth 1 -maxdepth 1 ! -name ".*" -printf "%f\\n" | sort')
        if layout.splitlines() != ['Documents', 'Downloads']:
            raise Failure('Fresh user home has unexpected visible entries: ' + layout)
        guest.root(password)
        root_state(guest, output, 'installed')
        network(guest, output, 'installed')
        record(output, 'packages.log', guest.run('''set -eu
for p in htop nano fastfetch xterm less procps iproute2 ca-certificates sudo bash dash openrc openrc-init busybox libpam-elogind; do dpkg-query -W -f='${binary:Package} ${Version} ${Status}\\n' "$p"; done
apt-config dump | grep '^APT::Install-Recommends "false";'
apt-config dump | grep '^APT::Install-Suggests "false";'
dpkg --audit
test -z "$(dpkg --audit)"
apt-get check
apt-get update
apt-get install --no-install-recommends -y hello
hello
apt-get remove -y hello
apt-get -s dist-upgrade > /tmp/bme-upgrade-check
cat /tmp/bme-upgrade-check
! grep -Eq '^Remv (openrc|openrc-init)( |$)|^Inst (systemd-sysv|sysvinit-core|runit-init)( |$)' /tmp/bme-upgrade-check
apt-get check
test -z "$(dpkg --audit)"
case "$(readlink /proc/1/exe)" in */openrc-init) ;; *) exit 1;; esac
''', timeout=1800))
        desktop(guest, password, output, 'verification')
        result['checks'].append('Disk-only boot, authenticated ash/sudo, home layout, UUID filesystems, DHCP/DNS, APT policy, package install/remove and upgrade plan')
        result['checks'].append('Ordinary-user rootless real VGA Xorg, Openbox and one xterm running ash')
        readings = []
        for boot in range(1, 4):
            guest.reboot()
            guest.login('tester', password)
            guest.root(password)
            root_state(guest, output, f'boot-{boot}')
            network(guest, output, f'boot-{boot}')
            desktop(guest, password, output, f'boot-{boot}')
            readings.append(memory(guest, output, boot))
            # Preserve each reading even if a later reboot or measurement fails.
            result['memory_readings'] = readings
            (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
            (output / 'memory.json').write_text(json.dumps({'configuration': CONFIG, 'readings': readings}, indent=2) + '\n')
        result['memory'] = summarize(readings)
        guest.poweroff()
        result['checks'].append('Three real reboots preserve disk and UEFI variables; final clean poweroff')
        if not result['memory']['accepted']:
            raise Failure('Desktop RAM acceptance failed; raw readings and process PSS remain visible')
        result['checks'].append('All three unrounded memory readings <=150 MiB and zero swap used')
        result['status'] = 'passed'
    except Exception as exc:
        result['error'] = str(exc)
        record(output, 'failure.log', traceback.format_exc())
        print(str(exc), file=sys.stderr)
    finally:
        if guest is not None:
            with suppress(Exception):
                guest.close()
        (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
        (output / 'memory.json').write_text(json.dumps({'configuration': CONFIG, 'readings': result.get('memory_readings', []), 'summary': result.get('memory')}, indent=2) + '\n')
        report = ['# Blue Mess Edition VM verification', '', f"Result: **{result['status'].upper()}**", '',
                  'Reference: amd64, 1 GiB RAM, 2 qemu64 vCPUs, pc-q35-8.2, TCG, std VGA, 1024×768.',
                  'Disk-only Openbox desktop with one idle xterm/ash; normal delivered services and working networking.', '',
                  '## Completed assertions', '']
        report += [f'- {check}' for check in result['checks']]
        report += ['', '## Desktop memory', '']
        for number, reading in enumerate(result.get('memory_readings', []), 1):
            report.append(f"- Boot {number}: {reading['used_MiB']} MiB; MemTotal={reading['MemTotal_kib']} KiB, MemAvailable={reading['MemAvailable_kib']} KiB; swap used={reading['SwapUsed_kib']} KiB; accepted={reading['accepted']}")
        if result['memory']:
            report.append(f"\nRange: {result['memory']['minimum_MiB']}–{result['memory']['maximum_MiB']} MiB.")
        if 'error' in result:
            report += ['', '## Failure or blocker', '', result['error']]
        report += ['', 'Installer raw memory is recorded separately in installer-meminfo.txt when the installer boots.',
                   'No result establishes a minimum physical RAM requirement. Missing readings are unmeasured.', '']
        (output / 'report.md').write_text('\n'.join(report))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
