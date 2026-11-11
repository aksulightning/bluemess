# Desktop script functionality

The three Alpine scripts are references for behavior, not scripts to run on
Debian. Sources: [asennus-low.sh](https://gitlab.com/aksulightning/toerkylaari/-/blob/main/projects/asennusskripti/asennus-low.sh),
[netti.sh](https://gitlab.com/aksulightning/toerkylaari/-/blob/main/projects/asennusskripti/netti.sh),
[valmis.sh](https://gitlab.com/aksulightning/toerkylaari/-/blob/main/projects/asennusskripti/valmis.sh).

| Original behavior | Blue Mess implementation |
| --- | --- |
| Openbox, XFCE panel/terminal, audio | Existing managed desktop and PipeWire lifecycle retained; no fixed UID 1000 or sleeps |
| Settings daemon, dark GTK theme | xfsettingsd, Debian Adwaita-dark defaults; existing user Xfconf settings preserved |
| NetworkManager and tray | Native OpenRC network-manager owner, nmtui/nmcli and nm-applet; normal polkit authorization |
| File/desktop/media tools | Thunar/GVfs, Mousepad, screenshot, GIMP, K3b, OBS, VLC, archive tools, GParted, Disks, udisks2 |
| GPU utilities and AMD firmware | Debian Mesa/Vulkan, firmware-amd-graphics, Xorg AMD driver, pciutils and usbutils; existing GPU helper retained |
| Podman | podman, uidmap, slirp4netns and fuse-overlayfs; cgroupfs and file events for OpenRC |
| Flatpak apps | Explicit per-user online `bluemess-install-flatpaks`; Firefox, Luanti, MenuLibre, Steam and GTK theme |
| Flatpak menu entries | Standard user/system export directories in XDG_DATA_DIRS; no copied launchers or dbus-launch wrappers |
| Shutdown, restart, logout launchers | Elogind/polkit for power actions; Openbox exits only the current session |
| Locale and keyboard | Existing installer prompts, including Finnish; no forced global locale |
| IceWM and wallpaper tools | icewm and feh available; existing solid blue desktop remains the default |

The original Windows startup sound is not downloaded or redistributed. The
AMD-only desktop detection, UID 1000 audio workaround, unrestricted Xwrapper
settings and disabled NetworkManager authorization are not carried over.
Debian package names are checked against the pinned snapshot: it uses
`network-manager-applet` and `network-manager-tui`, and Adwaita-dark instead of
Alpine's adw-gtk3. All native desktop tools are in the target manifest; Flatpak
downloads are deliberately separate so installation remains offline.

## Network ownership and existing systems

New targets enable network-manager; the minimal installer retains bme-network.
Each service refuses to start while the other is running or enabled. There is
one owner for DHCP, Wi-Fi and /etc/resolv.conf. NetworkManager stores new
connection profiles normally; it does not import bme-network's Wi-Fi file.

Upgrading bme-config preserves an existing system's current network owner and
does not terminate the session. After installing the new target packages and
bme-config, switch an existing machine at a local console:

```sh
sudo rc-update del bme-network default
sudo rc-update add network-manager default
sudo reboot
```

Then use `nmtui`, `nmcli` or the tray to configure Wi-Fi. Do not start both
services together. To undo, remove network-manager from its runlevel, restore
bme-network and its configuration, and reboot.

Run `bluemess-install-flatpaks` as the ordinary desktop user, without sudo.
Flatpak asks for confirmation and uses the user's Flathub remote. Its packages
are online upstream downloads, not part of the pinned Debian image. New users
get subordinate UID/GID ranges through Debian useradd; existing rootless Podman
users should verify their own entries in /etc/subuid and /etc/subgid. Do not
assign the same hard-coded range to multiple users.

The expanded application selection changes ISO size and potentially idle RAM.
The existing 350 MiB acceptance target is unchanged and must be remeasured with
all normal services running; it is not a result established by this change.
