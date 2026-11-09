# GPU driver preparation

Run this on an installed Blue Mess amd64 system after installing system updates.
If an update installed a new kernel, reboot into it first. The helper asks for
confirmation that updates have been installed; it does not perform a full system
upgrade or infer that all updates have been applied.

```sh
sudo bluemess-prepare-gpu-install
```

Select `nvidia` or `amd`, then answer the update question with `y` or `n`.
Answering `n` or reaching end of input stops before changes. You can also select
the GPU on the command line; the update confirmation still applies:

```sh
sudo bluemess-prepare-gpu-install nvidia
sudo bluemess-prepare-gpu-install amd
```

Choose the path for the GPU you intend to configure. The helper does not infer
which GPU should own the display on a hybrid system. APT retains its normal
transaction confirmation and locking. Unfinished dpkg operations or broken
dependencies stop preparation; fix those before retrying. Package removals are
not allowed by either path.

## NVIDIA: before running the vendor installer

The helper refuses to proceed if NVIDIA-specific packages are already installed
through APT, including NVIDIA libraries for another architecture. It prints the
conflicting package names for review; it does not purge them automatically.
Remove the conflicting packages through APT before choosing the `.run` route.
Do not mix the two driver installation methods.

Preparation writes `/etc/apt/preferences.d/00blue-mess-nvidia-run.pref`, pinning
NVIDIA-named packages and CUDA/NVCUVID/NVOPTIX/NVENC runtime library families to
priority `-1` for all architectures. This also blocks related NVIDIA utilities
and firmware packages. The generic GLVND libraries remain available. The pin
controls normal APT package selection; it is not a security boundary against
an administrator explicitly overriding APT policy or installing `.deb` files.

The helper enables Debian's `i386` architecture, refreshes APT metadata, and
simulates the requested transaction before installing:

- `build-essential`
- `dkms`
- `pkg-config`
- `libglvnd-dev`
- `libglvnd-dev:i386`
- `linux-headers-$(uname -r)` for the running kernel

If the exact headers are no longer available in Sid, boot the updated Debian
kernel and rerun the helper. Resolve any multiarch version or repository errors
before continuing. The helper does not change repository URLs, signature checks,
or Blue Mess's init-system exclusions.

Only after the dependencies and header check succeed does it write
`/etc/modprobe.d/blue-mess-disable-nouveau.conf`:

```conf
blacklist nouveau
options nouveau modeset=0
```

It rebuilds initramfs for all installed kernels and instructs you to reboot.
It does not unload Nouveau from a running display, change greetd, download a
driver, or launch a `.run` file. If desktop auto-start is enabled, disable it
as your ordinary user before rebooting:

```sh
bluemess-desktop auto-start false
```

After reboot, check that the following prints nothing:

```sh
lsmod | grep nouveau
```

If Nouveau is still loaded, stop and inspect other module-loading and initramfs
configuration before continuing. Exit any desktop session, then log in on tty2
or tty3 and follow NVIDIA's instructions for your downloaded `.run` file. Xorg
and OpenGL applications must be stopped. Enable DKMS integration when offered.
The helper cannot prevent you from manually launching the vendor installer too
early. Preparation is not evidence that a particular NVIDIA driver supports
your kernel or that graphics, login or device permissions work on your hardware.

## AMD: Debian packages

The AMD path installs `firmware-amd-graphics`, `libgl1-mesa-dri`, `libglx-mesa0`,
`mesa-vulkan-drivers`, and `xserver-xorg-video-amdgpu` through APT, then rebuilds
initramfs. Reboot afterward. No AMD `.run` installer is needed for this path.
The configured repositories must provide `non-free-firmware` for AMD firmware.

AMD preparation does not add i386, block APT drivers, blacklist Nouveau or AMD
modules, or remove settings from a previous NVIDIA preparation. If migrating
from NVIDIA, review the undo instructions separately.

## Retry and undo

The helper preserves identical configuration files on repeated runs and adds
i386 only if it is missing. Modified files or symlinks at its configuration paths
cause an error rather than being overwritten. Review or back up such files
before retrying. Concurrent copies of the helper are refused.

An APT failure may leave the NVIDIA pin, i386 architecture, and packages from
completed transactions installed. It does not create a new Nouveau blacklist
before the prerequisites succeed. If initramfs regeneration fails, the blacklist
may already exist and some initramfs files may have been updated: do not reboot
or run the `.run` installer until the error is fixed and preparation succeeds.

To abandon NVIDIA preparation, remove only the helper's two configuration files
and regenerate initramfs:

```sh
sudo rm -f /etc/apt/preferences.d/00blue-mess-nvidia-run.pref
sudo rm -f /etc/modprobe.d/blue-mess-disable-nouveau.conf
sudo update-initramfs -u -k all
```

Reboot only after regeneration succeeds. If a `.run` driver was subsequently
installed, first uninstall it with NVIDIA's uninstaller from a text console
with X stopped before switching to Nouveau or APT-managed NVIDIA drivers.
Inspect any additional blacklist files created by that installer separately.

Do not blindly remove build tools or i386 packages: they may be used by other
software. To remove i386 support, first review and remove the installed `:i386`
packages through APT; only then use `sudo dpkg --remove-architecture i386`.
There is no automatic package rollback for either GPU path.

## References

- [NVIDIA installation and kernel-header requirements](https://download.nvidia.com/XFree86/Linux-x86_64/595.80/README/installdriver.html)
- [Debian APT package pinning](https://manpages.debian.org/unstable/apt/apt_preferences.5.en.html)
- [Debian AMD graphics packages](https://wiki.debian.org/AtiHowTo)
