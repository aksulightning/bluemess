# Login shells only: /etc/profile is read by ash before the user profile.
# X terminals, tty2 and serial/remote logins are excluded by the command.
case $- in
    *i*) /usr/bin/bluemess-desktop --login ;;
esac
