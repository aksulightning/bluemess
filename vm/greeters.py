"""Real greeter transitions on the disposable guest created by verify.py."""
import shlex
import time

from verify import Failure, audio_playback, desktop, greeter_recovery, phase, record, text_login_recovery, wait_for_greeter, wait_for_service


def reboot_as_root(guest, password):
    guest.reboot()
    guest.login('tester', password)
    guest.root(password)


def wait_for_sddm_window(guest):
    # A running Qt process can still be loading its theme with a black screen.
    # Wait for its mapped, focused window before sending any login keystrokes.
    environment = guest.run('''set -eu
pid=$(pgrep -u sddm -f '^/usr/bin/sddm-greeter')
printf 'PID=%s\\n' "$pid"
tr '\\000' '\\n' < /proc/"$pid"/environ | grep -E '^(DISPLAY|XAUTHORITY)='
''')
    values = dict(line.split('=', 1) for line in environment.splitlines())
    if set(values) != {'PID', 'DISPLAY', 'XAUTHORITY'} or not values['PID'].isdigit():
        raise Failure('SDDM greeter lacks one PID and its X11 authentication environment')
    pid = values.pop('PID')
    xenv = 'runuser -u sddm -- env ' + ' '.join(shlex.quote(k + '=' + v) for k, v in values.items()) + ' '
    focus = '''import ctypes
x = ctypes.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes = [ctypes.c_char_p]
x.XOpenDisplay.restype = ctypes.c_void_p
x.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
x.XCloseDisplay.argtypes = [ctypes.c_void_p]
display = x.XOpenDisplay(None)
assert display, 'Cannot open the greeter display'
window, revert = ctypes.c_ulong(), ctypes.c_int()
x.XGetInputFocus(display, ctypes.byref(window), ctypes.byref(revert))
x.XCloseDisplay(display)
print(hex(window.value) if window.value > 1 else '')
'''
    return guest.run('set -eu\nn=0\nwhile :; do\n' +
                     'window=$(' + xenv + 'python3 -c ' + shlex.quote(focus) + ')\n' +
                     'if [ -n "$window" ] && ' + xenv + 'xprop -id "$window" _NET_WM_PID | grep -Eq ' +
                     shlex.quote(' = ' + pid + '$') + ' && ' +
                     xenv + 'xwininfo -id "$window" | grep -q "Map State: IsViewable"; then\n' +
                     '    printf "SDDM window ready: %s\\n" "$window"; break\nfi\n' +
                     'n=$((n+1)); test "$n" -le 90; sleep 1\ndone', timeout=120)


def sddm_prompt(guest, output, suffix):
    wait_for_service(guest, 'sddm')
    guest.run('''set -eu
rc-service sddm status
! rc-service greetd status
! rc-service bme-getty.tty1 status
n=0
until pgrep -u sddm -f '^/usr/bin/sddm-greeter' >/dev/null; do
    n=$((n+1)); test "$n" -le 90; sleep 1
done
! pgrep -u tester -x openbox
''', timeout=120)
    record(output, f'sddm-{suffix}-ready.log', wait_for_sddm_window(guest))
    guest.qmp.command('screendump', {'filename': str(output / f'sddm-{suffix}.ppm')})


def sddm_login(guest, password, output, suffix):
    phase(f'SDDM {suffix}: authenticate through the real graphical password field')
    sddm_prompt(guest, output, suffix + '-login')
    guest.qmp.chord('ctrl', 'a')
    guest.qmp.chord('backspace')
    guest.qmp.type(password + '\n')
    facts = guest.run('''set -eu
n=0
until pgrep -u tester -x openbox >/dev/null && pgrep -u tester -x xfce4-panel >/dev/null; do
    n=$((n+1)); test "$n" -le 120; sleep 1
done
n=0
until grep -Fxq 'Blue Mess session check passed.' /home/tester/.local/state/blue-mess/desktop.log; do
    n=$((n+1)); test "$n" -le 15; sleep 1
done
grep -Fx 'Service=sddm' /home/tester/.local/state/blue-mess/desktop.log
grep -Fx 'Type=x11' /home/tester/.local/state/blue-mess/desktop.log
for name in openbox xfce4-panel lxpolkit; do
    test "$(pgrep -u tester -x "$name" | wc -l)" -eq 1
done
pgrep -u tester -f '^xfce4-power-manager --no-daemon$'
test "$(stat -Lc '%u:%a' /run/user/$(id -u tester))" = "$(id -u tester):700"
cat /home/tester/.local/state/blue-mess/desktop.log
ps -eo pid,ppid,user,tty,args
''', timeout=180)
    record(output, f'sddm-{suffix}-session.log', facts)
    # SDDM creates a private /tmp/xauth_* file rather than ~/.Xauthority.
    environment = guest.run('''set -eu
pid=$(pgrep -u tester -x openbox)
tr '\\000' '\\n' < /proc/"$pid"/environ | grep -E '^(DISPLAY|XAUTHORITY|DBUS_SESSION_BUS_ADDRESS|XDG_RUNTIME_DIR)='
''')
    values = dict(line.split('=', 1) for line in environment.splitlines())
    if set(values) != {'DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR'}:
        raise Failure('SDDM desktop lacks display authentication or session environment')
    user = 'runuser -u tester -- env ' + ' '.join(shlex.quote(k + '=' + v) for k, v in values.items()) + ' '
    # The Openbox process exists before it publishes its window-manager window.
    guest.run('set -eu; n=0; until ' + user + "xprop -root _NET_SUPPORTING_WM_CHECK | grep -E 'window id # 0x[0-9a-f]+'; do n=$((n+1)); test \"$n\" -le 60; sleep 1; done", timeout=90)
    for attempt in range(3):
        if guest.run('pgrep -u tester -x xfce4-terminal || true').strip():
            break
        guest.qmp.chord('ctrl', 'alt', 't')
        guest.run('n=0; until pgrep -u tester -x xfce4-terminal >/dev/null; do n=$((n+1)); [ "$n" -le 10 ] || break; sleep 1; done', timeout=30)
    guest.run('pgrep -u tester -x xfce4-terminal')
    audio_playback(guest, output, 'sddm-' + suffix)
    guest.qmp.command('screendump', {'filename': str(output / f'sddm-{suffix}-desktop.ppm')})
    return user


def logout_sddm(guest, user, output, suffix):
    guest.run(user + 'openbox --exit')
    guest.run('''set -eu
n=0
while pgrep -u tester -x 'openbox|xfce4-panel|lxpolkit|pipewire|pipewire-pulse|wireplumber' >/dev/null; do
    n=$((n+1)); test "$n" -le 60; sleep 1
done
''', timeout=90)
    sddm_prompt(guest, output, suffix + '-logout')


def verify_choices(guest, password, output, result):
    import autostart
    phase('Verify default agetty, then save SDDM while the desktop is active')
    text_login_recovery(guest, output)
    desktop(guest, password, output, 'greeter-default')
    autostart.prepare(guest, output)
    record(output, 'switch-active-desktop.log', guest.run('''set -eu
pid=$(pgrep -u tester -x openbox)
bluemess-greeter-switcher sddm
test "$(pgrep -u tester -x openbox)" = "$pid"
rc-service bme-getty.tty1 status
! rc-service sddm status
# Exercise the real package maintainer path, preserving selection and session.
dpkg-reconfigure -f noninteractive bme-config
test "$(cat /etc/blue-mess/greeter)" = sddm
test "$(pgrep -u tester -x openbox)" = "$pid"
test ! -L /etc/runlevels/default/greetd
test ! -L /etc/runlevels/default/bme-getty.tty1
test "$(readlink /etc/runlevels/default/sddm)" = /etc/init.d/sddm
''', timeout=180))
    result['checks'].append('Default agetty authenticates and starts the desktop; choosing SDDM and reconfiguring the package preserve the active session')
    reboot_as_root(guest, password)
    autostart.check_boot(guest, output, 1)
    sddm_prompt(guest, output, 'first-boot')
    guest.qmp.type('incorrect\n')
    # PAM's rejection and the greeter's field reset are asynchronous. A fixed
    # four-second pause raced them on TCG and cleared part of the next password.
    guest.run('''set -eu
n=0
until grep -Fq 'pam_unix(sddm:auth): authentication failure' /var/log/messages; do
    n=$((n+1)); test "$n" -le 60; sleep 1
done
n=0
while pgrep -f '^/usr/lib/[^ ]*/sddm/sddm-helper .*--user tester( |$)' >/dev/null; do
    n=$((n+1)); test "$n" -le 60; sleep 1
done
! pgrep -u tester -x openbox
''', timeout=150)
    time.sleep(3)
    user = sddm_login(guest, password, output, 'first')
    autostart.check_desktop(guest, output, 1, 'first')
    logout_sddm(guest, user, output, 'first')
    result['checks'].append('SDDM rejects a wrong password; real graphical login starts the full Blue Mess session with elogind, D-Bus, panel, power manager, polkit, terminal and audible PipeWire output; logout returns to SDDM')
    user = sddm_login(guest, password, output, 'second')
    autostart.check_desktop(guest, output, 1, 'second-login')
    logout_sddm(guest, user, output, 'second')
    result['checks'].append('A second SDDM login/logout works without duplicate desktop or audio processes')
    reboot_as_root(guest, password)
    user = sddm_login(guest, password, output, 'reboot')
    autostart.check_boot(guest, output, 2)
    autostart.check_desktop(guest, output, 2, 'reboot')
    logout_sddm(guest, user, output, 'reboot')
    result['checks'].append('SDDM remains selected and authenticates after another reboot')
    result['checks'].append('Root and configured user autostart hooks run before login on two boots; service restart and repeated desktop login do not repeat commands; hooks retain the correct UID and environment')
    guest.run('bluemess-greeter-switcher agetty')
    reboot_as_root(guest, password)
    wait_for_service(guest, 'bme-getty.tty1')
    guest.run('''set -eu
rc-service bme-getty.tty1 status
! rc-service greetd status
! rc-service sddm status
test "$(cat /sys/class/tty/tty0/active)" = tty1
n=0; until grep -aq 'login:' /dev/vcs1; do n=$((n+1)); test "$n" -le 60; sleep 1; done
''', timeout=90)
    guest.qmp.type('tester\n')
    guest.run("n=0; until grep -aq 'Password:' /dev/vcs1; do n=$((n+1)); test \"$n\" -le 30; sleep 1; done", timeout=45)
    guest.qmp.type(password + '\n')
    guest.run("n=0; until ps -t tty1 -o user=,comm= | grep -Eq 'tester[[:space:]]+ash$'; do n=$((n+1)); test \"$n\" -le 30; sleep 1; done", timeout=45)
    guest.qmp.type('bluemess-desktop start\n')
    guest.run('n=0; until pgrep -u tester -x openbox; do n=$((n+1)); test "$n" -le 120; sleep 1; done', timeout=150)
    result['checks'].append('agetty selection survives reboot, selects tty1, authenticates with a password and launches the Blue Mess desktop')
    guest.run('bluemess-greeter-switcher tuigreet')
    reboot_as_root(guest, password)
    wait_for_greeter(guest, 'Username')
    guest.run('rc-service greetd status; test ! -L /etc/runlevels/default/sddm; test ! -L /etc/runlevels/default/bme-getty.tty1')
    result['checks'].append('Switching back restores tuigreet without competing tty1 services')
    # Keep the optional Debian greeter's real startup/recovery/authentication test.
    # A failure here remains visible even though new images use agetty.
    greeter_recovery(guest, output)
    desktop(guest, password, output, 'optional-tuigreet', greeter='tuigreet')
    guest.poweroff()
