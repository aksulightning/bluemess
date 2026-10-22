#!/usr/bin/ash
# Plain openbox bypasses openbox-session's XDG autostart helper.
xsetroot -solid '#174b88'
xrandr --output Virtual-1 --mode 1024x768 2>/dev/null || :
xterm -ls -e /usr/bin/ash &
exec dbus-run-session -- openbox
