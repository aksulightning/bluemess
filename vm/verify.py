#!/usr/bin/env python3
"""Real UEFI/TCG install, authenticated console/desktop and memory acceptance.

Only disposable qcow2 files created by this program are attached as hard disks.
No guest-side verification hook, fixture media or CI credential enters the ISO.
"""
import argparse
from array import array
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
import wave

from benchmark import MEMORY_LIMIT_MIB, parse_meminfo, summarize

CONFIG = {'architecture': 'amd64', 'ram_MiB': 1024, 'vcpus': 2,
          'machine': 'pc-q35-8.2', 'cpu': 'qemu64', 'acceleration': 'tcg',
          'graphics': 'std VGA', 'resolution': '1024x768',
          'audio': 'Intel HDA duplex, 48 kHz stereo s16 WAV capture',
          'settle_seconds': 60, 'fresh_boots': 3, 'swap_used_kib': 0,
          'metric': '(MemTotal_kib - MemAvailable_kib) / 1024',
          'threshold_MiB': MEMORY_LIMIT_MIB}


def phase(message):
    print(f'[{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}] {message}', flush=True)


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

    def chord(self, *codes):
        # Pace individual PS/2 transitions under TCG. QMP acknowledges enqueueing,
        # not guest delivery; a simultaneous chord can outrun guest input handling.
        def key(code, down):
            self.command('input-send-event', {'events': [{'type': 'key', 'data': {
                'down': down, 'key': {'type': 'qcode', 'data': code}}}]})
            time.sleep(.2)
        # Clear any inherited modifier state before pressing the chord.
        for code in reversed(codes):
            key(code, False)
        try:
            for code in codes:
                key(code, True)
        finally:
            for code in reversed(codes):
                key(code, False)

    def type(self, text):
        punctuation = {' ': 'spc', '\n': 'ret', '-': 'minus', '.': 'dot', '/': 'slash'}
        for char in text:
            code = punctuation.get(char, char)
            if not (char.isascii() and (char.islower() or char.isdigit() or char in punctuation)):
                raise Failure('Unsupported QMP keyboard input')
            self.command('send-key', {'keys': [{'type': 'qcode', 'data': code}], 'hold-time': 80})
            # TCG may process emulated keyboard interrupts later than QMP replies.
            # Leave a full key-release interval before sending the next character.
            time.sleep(.16)

    def close(self):
        self.stream.close()
        self.sock.close()


class Guest:
    def __init__(self, args, work, phase_name, disk, variables, network, iso=None, usb_media=False):
        phase(f'Launch {phase_name}: UEFI/TCG, networking={network}, USB media={usb_media}')
        self.buffer = ''
        self.redactions = []
        self.log = (work.parent / f'{phase_name}-serial.log').open('w', encoding='utf-8')
        qmp_path = work / f'{phase_name}.qmp'
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
        self.audio_path = work / f'{phase_name}-audio.wav'
        if not iso:
            command += ['-audiodev', f'wav,id=bmeaudio,path={self.audio_path},out.frequency=48000,out.channels=2,out.format=s16',
                        '-device', 'intel-hda', '-device', 'hda-duplex,audiodev=bmeaudio']
        if iso and usb_media:
            command += ['-device', 'qemu-xhci',
                        '-drive', f'if=none,id=installmedia,file={iso},format=raw,readonly=on',
                        '-device', 'usb-storage,drive=installmedia,bootindex=1']
        elif iso:
            command += ['-drive', f'file={iso},format=raw,media=cdrom,readonly=on']
        (work.parent / f'{phase_name}-qemu.json').write_text(json.dumps(command, indent=2) + '\n')
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
        phase(f'Authenticate serial console as {user}')
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
        phase('Authenticate administrative shell with sudo')
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
        phase('Request native OpenRC reboot')
        self.send('sync; openrc-shutdown --reboot now\n')
        # Next login() waits for a new real getty after the kernel boots again.

    def poweroff(self):
        phase('Request native OpenRC poweroff')
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
    phase(f'{suffix}: assert native PID 1, service state and system configuration')
    facts = guest.run('''set -eu
readlink /proc/1/exe
case "$(readlink /proc/1/exe)" in */openrc-init) ;; *) exit 1;; esac
rc-status --all
for service in bme-root udev bme-localmount bme-boot bme-network bme-syslog bme-klog dbus elogind chrony greetd bme-getty.tty2 bme-getty.tty3 bme-getty.ttyS0; do rc-service "$service" status; done
test "$(readlink /etc/runlevels/default/greetd)" = /etc/init.d/greetd
test ! -L /etc/runlevels/default/bme-getty.tty1
test ! -L /etc/runlevels/default/bme-getty.tty4
grep -qw console=tty4 /proc/cmdline
! grep -qw console=tty0 /proc/cmdline
# State markers alone are insufficient: assert the actual daemon processes.
ps -eo pid,ppid,user,args
for daemon in dbus-daemon elogind chronyd greetd; do
    pids=$(pgrep -x "$daemon") || { echo "Missing running daemon: $daemon" >&2; exit 1; }
    for pid in $pids; do readlink /proc/"$pid"/exe; done
done
pgrep -x systemd-udevd || pgrep -x udevd
for device in /dev/input/event*; do
    test -c "$device"
    stat -c '%G %n' "$device"
    test "$(stat -c %G "$device")" = input
done
dbus-send --system --type=method_call --print-reply --dest=org.freedesktop.DBus / org.freedesktop.DBus.ListNames
for service in dbus elogind chrony greetd; do
    test "$(pgrep -fc "^supervise-daemon $service --start ")" -eq 1
done
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
    phase(f'{suffix}: verify DHCP, route and DNS')
    facts = guest.run('''set -eu
n=0; until ip -4 route show default | grep -q default; do n=$((n+1)); test "$n" -le 90; sleep 1; done
ip -details address
ip route
cat /etc/resolv.conf
getent ahostsv4 deb.debian.org
''', timeout=180)
    record(output, f'network-{suffix}.log', facts)


def console_state(guest, output, suffix, stage):
    """Preserve actual console, process and logind state without relying on utmp."""
    guest.qmp.command('screendump', {'filename': str(output / f'console-{suffix}-{stage}.ppm')})
    facts = guest.run('''printf '%s\\n' '--- active VT ---'
cat /sys/class/tty/tty0/active; fgconsole
printf '%s\\n' '--- tty1 processes ---'
ps -t tty1 -o pid,ppid,user,tty,stat,args
printf '%s\\n' '--- tty1 settings ---'
stty -F /dev/tty1 -a
printf '%s\\n' '--- utmp (diagnostic only) ---'
ls -l /run/utmp; who
printf '%s\\n' '--- logind sessions ---'
loginctl list-sessions --no-legend
for session in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
    loginctl show-session "$session" -p Name -p TTY -p Active -p State -p Remote -p Service -p Class -p Seat
done
printf '%s\\n' '--- PAM session configuration ---'
cat /etc/pam.d/greetd /etc/pam.d/common-session
printf '%s\\n' '--- OpenRC boot log ---'
tail -n 120 /var/log/rc.log
printf '%s\\n' '--- system messages ---'
tail -n 120 /var/log/messages
printf '%s\\n' '--- desktop session log ---'
tail -n 120 /home/tester/.local/state/blue-mess/desktop.log
printf '%s\\n' '--- Xorg log ---'
tail -n 120 /home/tester/.local/share/xorg/Xorg.0.log
printf '%s\\n' '--- all processes ---'
for path in /var/log/Xorg.*.log /var/log/sddm.log /home/tester/.local/share/sddm/xorg-session.log; do
    [ ! -r "$path" ] || { printf '%s\\n' "$path"; tail -n 100 "$path"; }
done
ps -eo pid,ppid,user,tty,stat,args
''', timeout=30, check=False)
    record(output, f'console-{suffix}-{stage}.log', facts)


def wait_for_greeter(guest, prompt):
    guest.run(f'''set -eu
test -c /dev/vcs1
n=0
until grep -aiFq {shlex.quote(prompt)} /dev/vcs1 &&
      ps -t tty1 -o comm= | grep -Eq '^[[:space:]]*tuigreet$'; do
    n=$((n+1)); test "$n" -le 60 || exit 1; sleep 1
done
''', timeout=90)


def greeter_recovery(guest, output):
    """Exercise startup and one crash only at the unused guest login prompt."""
    phase('Verify greetd startup readiness and supervised crash recovery before login')
    wait_for_greeter(guest, 'Username')
    record(output, 'greeter-restart.log', guest.run('''set -eu
! ps -t tty1 -o user= | grep -qx '[[:space:]]*tester'
rc-service greetd restart
rc-service greetd status
''', timeout=45))
    wait_for_greeter(guest, 'Username')
    record(output, 'greeter-crash-recovery.log', guest.run('''set -eu
supervisor=$(cat /run/bme-greetd.pid)
daemon=$(pgrep -P "$supervisor" -x greetd)
test "$(printf '%s\\n' "$daemon" | wc -l)" -eq 1
kill -KILL "$daemon"
n=0
while :; do
    replacement=$(pgrep -P "$supervisor" -x greetd || :)
    if [ -n "$replacement" ] && [ "$replacement" != "$daemon" ]; then break; fi
    n=$((n+1)); test "$n" -le 15; sleep 1
done
test "$(cat /run/bme-greetd.pid)" = "$supervisor"
rc-service greetd status
printf 'greetd recovered: %s -> %s\\n' "$daemon" "$replacement"
''', timeout=30))
    wait_for_greeter(guest, 'Username')
    daemon = guest.run('pgrep -P "$(cat /run/bme-greetd.pid)" -x greetd').strip()
    if not daemon.isdigit():
        raise Failure('Expected exactly one supervised greetd daemon')
    return daemon


def desktop(guest, password, output, suffix, auto_start=False):
    phase(f'{suffix}: assert tty1 is selected before tuigreet login')
    guest.run('test "$(cat /sys/class/tty/tty0/active)" = tty1')
    console_state(guest, output, suffix, 'before-login')
    try:
        wait_for_greeter(guest, 'Username')
        guest.qmp.type('tester\n')
        # Read the real VT text before sending a secret. This confirms QMP input
        # reached tuigreet and prevents typing a password at a username/shell prompt.
        wait_for_greeter(guest, 'Password:')
        phase(f'{suffix}: tuigreet displays the PAM password prompt on tty1')
        guest.qmp.type(password + '\n')
        # Successful password login must produce both a tester-owned ash on tty1
        # and the active PAM/logind login session for that same user and VT.
        # who is retained as evidence but cannot be the gate when utmp is absent.
        tty_login = guest.run('''set -eu
tester_uid=$(id -u tester)
n=0
while :; do
    shell_ok=0
    for pid in $(ps -t tty1 -o pid=,user= | awk '$2 == "tester" {print $1}'); do
        case "$(readlink /proc/"$pid"/exe 2>/dev/null || :)" in */busybox)
            if tr '\\000' ' ' < /proc/"$pid"/cmdline | grep -Eq '(^|/|-| )ash( |$)' &&
               tr '\\000' '\\n' < /proc/"$pid"/environ | grep -Fxq "XDG_RUNTIME_DIR=/run/user/$tester_uid"; then
                shell_ok=1
            fi;;
        esac
    done
    session_ok=0
    for session in $(loginctl list-sessions --no-legend | awk '$3 == "tester" {print $1}'); do
        properties=$(loginctl show-session "$session" -p Name -p TTY -p Active -p Service -p Remote -p Seat)
        if printf '%s\\n' "$properties" | grep -qx 'Name=tester' &&
           printf '%s\\n' "$properties" | grep -qx 'TTY=tty1' &&
           printf '%s\\n' "$properties" | grep -qx 'Active=yes' &&
           printf '%s\\n' "$properties" | grep -qx 'Seat=seat0' &&
           printf '%s\\n' "$properties" | grep -qx 'Service=greetd' &&
           printf '%s\\n' "$properties" | grep -qx 'Remote=no'; then
            session_ok=1
            printf '%s\\n' "$properties"
        fi
    done
    [ "$shell_ok" -eq 1 ] && [ "$session_ok" -eq 1 ] && break
    n=$((n+1)); test "$n" -le 90 || exit 1; sleep 1
done
test "$(stat -Lc '%u:%a' "/run/user/$tester_uid")" = "$tester_uid:700"
ps -t tty1 -o pid,ppid,user,tty,stat,args
''', timeout=150)
        record(output, f'tty1-authentication-{suffix}.log', tty_login)
        console_state(guest, output, suffix, 'after-login')
    except Exception:
        with suppress(Exception):
            console_state(guest, output, suffix, 'login-failed')
        raise
    phase(f'{suffix}: tty1 authenticated with ash and active logind session; start real Xorg/Openbox')
    if not auto_start:
        guest.qmp.type('bluemess-desktop start\n')
    guest.run('''n=0; until pgrep -u tester -x openbox >/dev/null; do n=$((n+1)); test "$n" -le 180 || { cat /home/tester/.local/share/xorg/Xorg.0.log; exit 1; }; sleep 1; done''', timeout=240)
    guest.run('''set -eu
for log in login-check desktop; do
    grep -Fx 'Blue Mess session check' "/home/tester/.local/state/blue-mess/$log.log"
done
''')
    # Select the same resolution on the real guest VGA server on every boot.
    guest.run('runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority xrandr -s 1024x768')
    # Process creation precedes Openbox's keyboard grabs. Wait for the real
    # window-manager property and panel before delivering the terminal shortcut.
    guest.run('''set -eu
n=0
until runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority xprop -root _NET_SUPPORTING_WM_CHECK | grep -Eq 'window id # 0x[0-9a-f]+'; do
    n=$((n+1)); test "$n" -le 60; sleep 1
done
n=0; until pgrep -u tester -x xfce4-panel >/dev/null; do n=$((n+1)); test "$n" -le 60; sleep 1; done
''', timeout=150)
    for attempt in range(3):
        if guest.run('pgrep -u tester -x xfce4-terminal || true').strip():
            break
        guest.qmp.chord('ctrl', 'alt', 't')
        # A shortcut sent during final startup may precede the keyboard grab.
        # Wait before retrying, and never send another once the process exists.
        if guest.run('''n=0; until pgrep -u tester -x xfce4-terminal >/dev/null; do n=$((n+1)); [ "$n" -le 10 ] || break; sleep 1; done; pgrep -u tester -x xfce4-terminal || true''', timeout=30).strip():
            break
    facts = guest.run('''set -eu
n=0; until pgrep -u tester -x xfce4-terminal >/dev/null; do n=$((n+1)); test "$n" -le 90; sleep 1; done
test "$(pgrep -u tester -x xfce4-terminal | wc -l)" -eq 1
test "$(readlink -f /usr/bin/x-terminal-emulator)" = /usr/bin/xfce4-terminal.wrapper
# The delivered panel and power manager must be present during every benchmark.
n=0
until pgrep -u tester -x xfce4-panel >/dev/null && pgrep -u tester -f '^xfce4-power-manager --no-daemon$' >/dev/null; do
    n=$((n+1)); test "$n" -le 60; sleep 1
done
test "$(pgrep -u tester -x xfce4-panel | wc -l)" -eq 1
test "$(pgrep -u tester -f '^xfce4-power-manager --no-daemon$' | wc -l)" -eq 1
pgrep -u tester -x lxpolkit
dbus-send --system --print-reply --dest=org.freedesktop.UPower /org/freedesktop/UPower org.freedesktop.UPower.EnumerateDevices
runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority xset q
runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority xset q | grep -Eq 'timeout:[[:space:]]+0[[:space:]]+cycle:'
# A server without DPMS is also acceptable; otherwise it must be disabled.
! runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority xset q | grep -q 'DPMS is Enabled'

xpid=$(pgrep -u tester -x Xorg); test -n "$xpid"
obpid=$(pgrep -u tester -x openbox); test -n "$obpid"
tpid=$(pgrep -u tester -x xfce4-terminal); test -n "$tpid"
# GTK/VTE creates the terminal process before it forks the interactive shell.
# Wait for that child rather than treating process creation as shell readiness.
n=0
while :; do
    child=$(ps -o pid= --ppid "$tpid" | head -n 1 | tr -d ' ')
    if [ -n "$child" ] && [ -e /proc/"$child"/exe ]; then
        case "$(readlink /proc/"$child"/exe)" in */busybox) break ;; esac
    fi
    n=$((n+1)); test "$n" -le 30; sleep 1
done
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



def console_layout(guest, password, output):
    """Use real F-key switching, password logins, and diagnostic output probes."""
    phase('Verify tty1/2/3 login layout and diagnostics-only tty4')
    wait_for_greeter(guest, 'Username')
    guest.run('test "$(cat /sys/class/tty/tty0/active)" = tty1')
    def switch(vt):
        guest.qmp.command('send-key', {'keys': [{'type': 'qcode', 'data': key}
                                               for key in ('ctrl', 'alt', f'f{vt}')], 'hold-time': 200})
        guest.run(f'n=0; until test "$(cat /sys/class/tty/tty0/active)" = tty{vt}; do n=$((n+1)); test "$n" -le 30 || exit 1; sleep 1; done')
    for vt in (2, 3):
        switch(vt)
        guest.run(f'''n=0; until grep -aFq 'login:' /dev/vcs{vt}; do
    n=$((n+1)); test "$n" -le 30 || exit 1; sleep 1
done''')
        guest.qmp.type('tester\n')
        guest.run(f'''n=0; until grep -aFq 'Password:' /dev/vcs{vt}; do
    n=$((n+1)); test "$n" -le 30 || exit 1; sleep 1
done''')
        guest.qmp.type(password + '\n')
        guest.run(f'''n=0; until ps -t tty{vt} -o user=,comm= | grep -Eq 'tester[[:space:]]+ash$'; do
    n=$((n+1)); test "$n" -le 30 || exit 1; sleep 1
done''')
        guest.qmp.type('exit\n')
    nonce = 'bme-diagnostic-' + secrets.token_hex(6)
    facts = guest.run(f'''set -eu
printf '<6>{nonce}-kernel\\n' > /dev/kmsg
printf '{nonce}-console\\n' > /dev/console
logger -t bme-verify {nonce}-syslog
n=0; until grep -aFq {nonce}-syslog /dev/vcs4; do
    n=$((n+1)); test "$n" -le 30; sleep 1
done
grep -aFq {nonce}-kernel /dev/vcs4
grep -aFq {nonce}-console /dev/vcs4
! grep -aFq {nonce} /dev/vcs1
! ps -t tty4 -o comm= | grep -Eq '(agetty|login|ash|tuigreet)'
for vt in 4 5 6; do test ! -L /etc/runlevels/default/bme-getty.tty$vt; done
cat /proc/cmdline
ps -eo pid,tty,comm
''')
    record(output, 'console-routing.log', facts)
    switch(4)
    guest.qmp.command('screendump', {'filename': str(output / 'diagnostics-tty4.ppm')})
    switch(1)


def audio_playback(guest, output, suffix, recover=False):
    """Capture PCM after the emulated sound card, not just a responding socket."""
    phase(f'{suffix}: verify automatic PipeWire startup and captured playback')
    user = 'runuser -u tester -- env XDG_RUNTIME_DIR=/run/user/$(id -u tester) '
    facts = guest.run('''set -eu
n=0
until ''' + user + '''bluemess-audio status; do
    n=$((n+1)); test "$n" -le 30; sleep 1
done
for daemon in pipewire wireplumber pipewire-pulse; do
    test "$(pgrep -u tester -x "$daemon" | wc -l)" -eq 1
done
''' + user + '''pactl info
''' + user + '''pactl info | grep -F PipeWire
cat /proc/asound/cards
''', timeout=180)
    record(output, f'audio-{suffix}.log', facts)
    if recover:
        guest.run('''set -eu
old=$(pgrep -u tester -x pipewire-pulse)
kill "$old"
n=0
until test "$(pgrep -u tester -x pipewire-pulse)" != "$old" &&
      ''' + user + '''bluemess-audio status >/dev/null 2>&1; do
    n=$((n+1)); test "$n" -le 45; sleep 1
done
''' + user + '''bluemess-audio restart
''', timeout=180)
    # The WAV backend updates its header on close. During the run, examine
    # newly appended stereo s16 PCM and save a standalone finalized excerpt.
    offset = max(44, guest.audio_path.stat().st_size if guest.audio_path.exists() else 44)
    offset += (-offset) % 4
    guest.run(user + 'bluemess-audio test', timeout=30)
    time.sleep(2)
    with guest.audio_path.open('rb') as stream:
        stream.seek(offset)
        pcm = stream.read()
    pcm = pcm[:len(pcm) // 4 * 4]
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    nonzero = sum(abs(sample) > 32 for sample in samples)
    if nonzero < 1000:
        raise Failure(f'{suffix}: emulated sound output is silent or absent ({nonzero} audible samples)')
    with wave.open(str(output / f'audio-{suffix}.wav'), 'wb') as recording:
        recording.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
        recording.writeframes(pcm)
    result = {'passed': True, 'samples': len(samples), 'audible_samples': nonzero,
              'capture': f'audio-{suffix}.wav'}
    record(output, f'audio-{suffix}.json', json.dumps(result, indent=2))
    return result


def window_interactions(guest, output):
    """Exercise actual titlebar dragging, then keyboard resizing on the real VT."""
    phase('Verify real titlebar mouse drag and keyboard window resizing')
    xenv = 'runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority '
    window = guest.run(xenv + """/usr/bin/ash -c '
tpid=$(pgrep -u tester -x xfce4-terminal)
for window in $(xprop -root _NET_CLIENT_LIST | sed "s/.*# //; s/,//g"); do
    if xprop -id "$window" _NET_WM_PID | grep -Eq "= $tpid$"; then printf "%s" "$window"; exit 0; fi
done
exit 1
'""")
    if not re.fullmatch(r'0x[0-9a-fA-F]+', window):
        raise Failure('Could not identify the test xfce4-terminal window')

    def geometry():
        info = guest.run(xenv + f'xwininfo -id {window}')
        fields = ('Absolute upper-left X', 'Absolute upper-left Y', 'Width', 'Height')
        return tuple(int(re.search(re.escape(field) + r':\s*(-?\d+)', info).group(1)) for field in fields)

    before = geometry()
    extents = guest.run(xenv + f'xprop -id {window} _NET_FRAME_EXTENTS')
    top = int(extents.split('=')[1].split(',')[2])
    if top <= 0:
        raise Failure('Test xfce4-terminal has no titlebar to drag')
    # Use one XTEST input device for positioning, pressing and motion. Mixing
    # XWarpPointer with a separate emulated PS/2 device can move the cursor at
    # the first button event. These are real pointer events consumed by Openbox,
    # not a window-manager request to move the window programmatically.
    pointer_x = before[0] + min(80, before[2] // 2)
    pointer_y = before[1] - max(1, top // 2)
    drag = f"""import ctypes as c, time
x = c.CDLL('libX11.so.6')
t = c.CDLL('libXtst.so.6')
x.XOpenDisplay.restype = c.c_void_p
x.XSync.argtypes = [c.c_void_p, c.c_int]
x.XCloseDisplay.argtypes = [c.c_void_p]
t.XTestFakeMotionEvent.argtypes = [c.c_void_p, c.c_int, c.c_int, c.c_int, c.c_ulong]
t.XTestFakeButtonEvent.argtypes = [c.c_void_p, c.c_uint, c.c_int, c.c_ulong]
d = x.XOpenDisplay(None)
assert d, 'Cannot open the real X display'
def flush():
    x.XSync(d, 0)
    time.sleep(.2)
try:
    assert t.XTestFakeMotionEvent(d, 0, {pointer_x}, {pointer_y}, 0)
    flush()
    assert t.XTestFakeButtonEvent(d, 1, 1, 0)
    flush()
    for step in range(1, 9):
        assert t.XTestFakeMotionEvent(d, 0, {pointer_x} + step * 6, {pointer_y} + step * 3, 0)
        flush()
finally:
    t.XTestFakeButtonEvent(d, 1, 0, 0)
    flush()
    x.XCloseDisplay(d)
"""
    record(output, 'openbox-tested-config.xml', guest.run('cat /home/tester/.config/openbox/rc.xml'))
    guest.run(xenv + 'python3 -c ' + shlex.quote(drag))
    after_move = geometry()
    facts = {'window': window, 'before': before, 'after_titlebar_drag': after_move}
    record(output, 'window-interactions.json', json.dumps(facts, indent=2))
    if abs(after_move[0] - before[0]) < 20 or abs(after_move[1] - before[1]) < 10:
        raise Failure(f'Titlebar drag did not move xfce4-terminal: {before} -> {after_move}')
    guest.qmp.command('send-key', {'keys': [{'type': 'qcode', 'data': 'alt'}, {'type': 'qcode', 'data': 'f8'}], 'hold-time': 200})
    time.sleep(.5)
    # Openbox uses the first arrow to select the resize edge; only a
    # subsequent arrow changes the size (resize_with_keys in moveresize.c).
    for _ in range(2):
        guest.qmp.command('send-key', {'keys': [{'type': 'qcode', 'data': 'right'}], 'hold-time': 200})
        time.sleep(.5)
    guest.qmp.command('send-key', {'keys': [{'type': 'qcode', 'data': 'ret'}], 'hold-time': 200})
    time.sleep(.5)
    after_resize = geometry()
    facts['after_keyboard_resize'] = after_resize
    record(output, 'window-interactions.json', json.dumps(facts, indent=2))
    if after_resize[2] <= after_move[2]:
        raise Failure(f'Keyboard resize did not widen xfce4-terminal: {after_move} -> {after_resize}')


def memory(guest, output, boot):
    phase(f'Memory boot {boot}: settle for {CONFIG["settle_seconds"]} seconds')
    # The only activity during settling is QEMU's ordinary delivered guest services.
    time.sleep(CONFIG['settle_seconds'])
    reading = record(output, f'meminfo-boot-{boot}.txt', guest.run('cat /proc/meminfo'))
    result = parse_meminfo(reading)
    phase(f'Memory boot {boot}: {result["used_MiB"]} MiB, swap={result["SwapUsed_kib"]} KiB, accepted={result["accepted"]}')
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
    parser.add_argument('--greeters-only', action='store_true',
                        help='Run the installed greeter matrix; not the release/RAM acceptance suite')
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
        phase('USB boot: verify offline payload and rejection of installation medium')
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
        phase('Optical boot: run the actual offline installer on disposable /dev/vda')
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
        if args.greeters_only:
            from greeters import verify_choices
            result['scope'] = 'greeters-only; not release or memory acceptance'
            verify_choices(guest, password, output, result)
            result['status'] = 'passed'
            return 0
        network(guest, output, 'installed')
        phase('Installed system: verify packages/APT policy, install/remove hello and simulate upgrade')
        record(output, 'packages.log', guest.run('''set -eu
for p in htop nano fastfetch xterm xfce4-terminal less procps iproute2 ca-certificates sudo bash dash openrc openrc-init busybox libpam-elogind greetd tuigreet xfce4-panel xfce4-power-manager xfconf upower polkitd pkexec lxpolkit build-essential linux-headers-amd64 dkms lua5.4 pipewire pipewire-pulse pipewire-alsa wireplumber pulseaudio-utils pavucontrol alsa-ucm-conf firmware-sof-signed firmware-intel-sound; do dpkg-query -W -f='${binary:Package} ${Version} ${Status}\\n' "$p"; done
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
        result['checks'].append('Disk-only boot, authenticated ash/sudo, home layout, UUID filesystems, DHCP/DNS, APT policy, package install/remove and upgrade plan')
        console_layout(guest, password, output)
        result['checks'].append('TTY1 selected at boot; tty2/tty3 authenticate; kernel, console and syslog probes reach tty4 without a login there')
        greeter_pid = greeter_recovery(guest, output)
        result['checks'].append('greetd starts through its readiness hook and OpenRC restores the greeter after a daemon crash before login')
        desktop(guest, password, output, 'verification')
        result['audio'] = [audio_playback(guest, output, 'verification', recover=True)]
        result['checks'].append('Automatic PipeWire audio, process recovery, restart and non-silent emulated HDA playback')
        result['checks'].append('Ordinary-user rootless Xorg/Openbox, one panel/power manager/authentication agent, UPower, no idle screen blanking and one xfce4-terminal/ash')
        window_interactions(guest, output)
        result['checks'].append('Actual XTEST titlebar drag moves the xfce4-terminal window and Alt+F8 keyboard resizing changes its width')
        guest.run('test "$(pgrep -P "$(cat /run/bme-greetd.pid)" -x greetd)" = ' + shlex.quote(greeter_pid))
        result['checks'].append('The same greetd daemon remains running throughout the authenticated desktop checks')
        phase('Verify desktop logout cleans up its companion processes and returns to tty1')
        record(output, 'desktop-logout.log', guest.run('''set -eu
runuser -u tester -- env DISPLAY=:0 XAUTHORITY=/home/tester/.Xauthority openbox --exit
n=0
while pgrep -u tester -x 'pipewire|wireplumber|pipewire-pulse' >/dev/null || pgrep -u tester -x Xorg >/dev/null || pgrep -u tester -x xfce4-panel >/dev/null || pgrep -u tester -x lxpolkit >/dev/null || pgrep -u tester -f '^xfce4-power-manager --no-daemon$' >/dev/null; do
    n=$((n+1)); test "$n" -le 60; sleep 1
done
ps -t tty1 -o pid,ppid,user,comm,args
ps -t tty1 -o user=,comm= | grep -E 'tester[[:space:]]+ash$'
''', timeout=90))
        result['checks'].append('Desktop logout stops Xorg, panel, power manager and authentication agent and leaves the authenticated tty1 shell')
        phase('Verify tty1 shell logout returns to tuigreet')
        guest.qmp.type('exit\n')
        wait_for_greeter(guest, 'Username')
        result['checks'].append('greetd authenticates tuigreet on tty1, assigns an active seat0 and user runtime directory, and restores the greeter at shell logout')
        phase('Verify toolchain, matching kernel headers and Lua; enable tty1 auto-start for benchmark boots')
        record(output, 'development-tools.log', guest.run('''set -eu
work=$(mktemp -d /tmp/bme-toolchain.XXXXXX)
printf '#include <stdio.h>\\nint main(void) { puts("toolchain-ok"); return 0; }\\n' > "$work/hello.c"
cc "$work/hello.c" -o "$work/hello"
"$work/hello" | grep -x toolchain-ok
lua5.4 -e 'assert(6 * 7 == 42); print(_VERSION)'
dkms status
test -f "/lib/modules/$(uname -r)/build/Makefile"
printf '#include <linux/module.h>\\nMODULE_LICENSE("GPL");\\n' > "$work/bme_probe.c"
printf 'obj-m := bme_probe.o\\n' > "$work/Makefile"
make -s -C "/lib/modules/$(uname -r)/build" M="$work" modules
test -s "$work/bme_probe.ko"
rm -rf "$work"
runuser -u tester -- bluemess-desktop status | grep -x 'Desktop auto-start: false'
runuser -u tester -- bluemess-desktop auto-start true
runuser -u tester -- bluemess-desktop status | grep -x 'Desktop auto-start: true'
runuser -u tester -- bluemess-desktop auto-start false
runuser -u tester -- bluemess-desktop status | grep -x 'Desktop auto-start: false'
runuser -u tester -- bluemess-desktop auto-start true
''', timeout=300))
        result['checks'].append('C compilation, Lua execution, matching kernel-header module build, DKMS presence and persistent user auto-start toggle')
        readings = []
        for boot in range(1, 4):
            phase(f'Begin fresh installed-system benchmark boot {boot}/3')
            guest.reboot()
            guest.login('tester', password)
            guest.root(password)
            root_state(guest, output, f'boot-{boot}')
            network(guest, output, f'boot-{boot}')
            desktop(guest, password, output, f'boot-{boot}', auto_start=True)
            result['audio'].append(audio_playback(guest, output, f'boot-{boot}'))
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
        result['checks'].append(f'All three unrounded memory readings <={MEMORY_LIMIT_MIB} MiB and zero swap used')
        result['status'] = 'passed'
    except Exception as exc:
        result['error'] = str(exc)
        record(output, 'failure.log', traceback.format_exc())
        print(str(exc), file=sys.stderr, flush=True)
        if guest is not None:
            # QMP screenshot is independent of a working guest serial shell.
            with suppress(Exception):
                guest.qmp.command('screendump', {'filename': str(output / 'failure-console.ppm')})
            with suppress(Exception):
                guest.qmp.command('send-key', {'keys': [{'type': 'qcode', 'data': key}
                                                       for key in ('ctrl', 'alt', 'f4')], 'hold-time': 200})
                time.sleep(1)
                guest.qmp.command('screendump', {'filename': str(output / 'failure-diagnostics-tty4.ppm')})
            with suppress(Exception):
                console_state(guest, output, 'failure', 'final')
    finally:
        if guest is not None:
            with suppress(Exception):
                guest.close()
        result_file = 'greeter-results.json' if args.greeters_only else 'results.json'
        (output / result_file).write_text(json.dumps(result, indent=2) + '\n')
        (output / 'memory.json').write_text(json.dumps({'configuration': CONFIG, 'readings': result.get('memory_readings', []), 'summary': result.get('memory')}, indent=2) + '\n')
        report = ['# Blue Mess Edition VM verification', '', f"Result: **{result['status'].upper()}**", '',
                  'Reference: amd64, 1 GiB RAM, 2 qemu64 vCPUs, pc-q35-8.2, TCG, std VGA, 1024×768.',
                  'Disk-only Openbox desktop with XFCE panel/power manager and one idle xfce4-terminal/ash; normal delivered services and working networking.', '',
                  '## Completed assertions', '']
        if args.greeters_only:
            report = ['# Blue Mess greeter verification', '', f"Result: **{result['status'].upper()}**", '',
                      'Focused login-manager matrix on a freshly installed disposable QEMU disk.',
                      'This is not a validated release or a RAM acceptance result.', '', '## Completed assertions', '']
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
