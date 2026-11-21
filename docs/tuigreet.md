# Debian tuigreet

New images install the official Debian `tuigreet` 0.9.1-7 amd64 binary from
the signed Sid snapshot `20261121T023257Z`. Both installer and target use this
same snapshot. `build/inputs.env` records the expected version; image assembly
checks that the installed package matches and that `tuigreet-bme` is absent.
No local tuigreet patches or Rust package build are applied.

The command remains `/usr/bin/tuigreet`; greetd, PAM, the selected login manager
and the native OpenRC integration keep their existing configuration. The
switcher option is `tuigreet`, not the former package name `tuigreet-bme`.

## Existing installations

Installing a new `bme-config` package alone does not replace `tuigreet-bme` or
change an installed system's APT sources. From a recovery console (tty2/tty3),
first update the existing Blue Mess Debian source entry to the snapshot below.
Preserve the other APT policy and avoid adding a second, moving Sid source:

```text
deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261121T023257Z/ sid main non-free-firmware
```

Then inspect and perform the replacement explicitly:

```sh
sudo apt-get update
apt-cache policy tuigreet tuigreet-bme
sudo apt-get -s install --no-install-recommends tuigreet=0.9.1-7 tuigreet-bme-
sudo apt-get install --no-install-recommends tuigreet=0.9.1-7 tuigreet-bme-
dpkg-query -W -f='${binary:Package} ${Version} ${Status}\n' tuigreet
```

The trailing minus requests removal of the temporary package in the same APT
transaction. Review the simulated removals and dependency changes before the
real transaction. This does not request a full system upgrade. Reboot when
ready to use the replacement; do not restart greetd during an active tty1
session. If selecting it again is needed, use
`sudo bluemess-greeter-switcher tuigreet` before rebooting.

## Validation and known limitation

Debian 0.9.1-7 changes maintainer metadata relative to 0.9.1-6. Its Debian patch
series does not include the terminal-startup backport or exit-cleanup patch
previously shipped in `tuigreet-bme`. The replacement is an explicit return to
the official Debian binary, not a claim that the reported greeter bugs are fixed.
[Debian #1153617](https://bugs.debian.org/1153617) reports the startup race in
0.9.1-7; its status was pending when checked on 2026-11-21.

The package workflow installs the official binary with signature verification
and runs `build/check-tuigreet-pty.py`. It retains the delayed cursor replies,
keyboard/session IPC and clean-exit checks; failures remain failures. The
greeter workflow exercises the real login-manager transitions. The snapshot
workflow runs the full offline installation, desktop and three-boot memory
suite on disposable QEMU disks. Neither replaces testing on the affected
OptiPlex/Quadro T400. Actual outcomes are recorded in [status.md](status.md).

References: [Debian changelog](https://metadata.ftp-master.debian.org/changelogs/main/t/tuigreet/tuigreet_0.9.1-7_changelog),
[snapshot package history](https://snapshot.debian.org/package/tuigreet/).
