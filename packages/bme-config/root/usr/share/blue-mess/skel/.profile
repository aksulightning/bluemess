# Blue Mess Edition: BusyBox ash login profile.
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin
export EDITOR=nano
export PAGER=less
export ENV="$HOME/.ashrc"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_DATA_HOME="$HOME/.local/share"
[ ! -f "$HOME/.ashrc" ] || . "$HOME/.ashrc"

# Blue Mess desktop login hook
case $- in
    *i*) /usr/bin/bluemess-desktop --login ;;
esac
