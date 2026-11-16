"""Autostart probes installed only into the verifier's disposable guest."""
from verify import record


def prepare(guest, output):
    record(output, 'autostart-setup.log', guest.run('''set -eu
install -d -m 755 /etc/blue-mess/autostart.d
install -d -o tester -g tester /home/tester/.config/blue-mess/boot.d /home/tester/.config/blue-mess/autostart.d
cat > /etc/blue-mess/autostart.d/10-vm-probe.sh <<'HOOK'
#!/usr/bin/ash
set -eu
test "$(id -u)" = 0
test -z "$(who)"
cat /proc/sys/kernel/random/boot_id >> /var/lib/blue-mess/autostart-probe
HOOK
cat > /home/tester/.config/blue-mess/boot.d/10-vm-probe.sh <<'HOOK'
#!/usr/bin/ash
set -eu
test "$(id -un)" = tester
test -z "${DISPLAY:-}${DBUS_SESSION_BUS_ADDRESS:-}"
test -z "$(who)"
cat /proc/sys/kernel/random/boot_id >> "$HOME/.local/state/blue-mess/boot-probe"
HOOK
cat > /home/tester/.config/blue-mess/autostart.d/10-vm-probe.sh <<'HOOK'
#!/usr/bin/ash
set -eu
test "$(id -un)" = tester
test -n "$DISPLAY"; test -n "$DBUS_SESSION_BUS_ADDRESS"
cat /proc/sys/kernel/random/boot_id >> "$HOME/.local/state/blue-mess/desktop-probe"
HOOK
chmod 755 /etc/blue-mess/autostart.d/10-vm-probe.sh /home/tester/.config/blue-mess/boot.d/10-vm-probe.sh /home/tester/.config/blue-mess/autostart.d/10-vm-probe.sh
chown -R tester:tester /home/tester/.config/blue-mess
printf 'tester\\n' > /etc/blue-mess/autostart-users
test ! -e /var/lib/blue-mess/autostart-probe
'''))


def check_boot(guest, output, count):
    record(output, f'autostart-boot-{count}.log', guest.run(f'''set -eu
test "$(cat /etc/blue-mess/autostart-users)" = tester
rc-service bme-autostart status
for probe in /var/lib/blue-mess/autostart-probe /home/tester/.local/state/blue-mess/boot-probe; do
    test "$(wc -l < "$probe")" -eq {count}
    test "$(tail -n 1 "$probe")" = "$(cat /proc/sys/kernel/random/boot_id)"
done
# Restarting the system wrapper must not replay either scope.
rc-service bme-autostart restart
test "$(wc -l < /var/lib/blue-mess/autostart-probe)" -eq {count}
test "$(wc -l < /home/tester/.local/state/blue-mess/boot-probe)" -eq {count}
test "$(stat -c %U /home/tester/.local/state/blue-mess/boot-probe)" = tester
'''))


def check_desktop(guest, output, count, suffix):
    record(output, f'autostart-desktop-{suffix}.log', guest.run(f'''set -eu
probe=/home/tester/.local/state/blue-mess/desktop-probe
n=0
until test -f "$probe" && test "$(wc -l < "$probe")" -eq {count}; do
    n=$((n+1)); test "$n" -le 30; sleep 1
done
test "$(tail -n 1 "$probe")" = "$(cat /proc/sys/kernel/random/boot_id)"
test "$(stat -c %U "$probe")" = tester
bluemess-autostart status
''', timeout=45))
