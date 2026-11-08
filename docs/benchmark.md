# Desktop acceptance benchmark

The release gate is an actual installed-system measurement, not a package-size estimate. No memory result has been established merely by adding the harness. Read `verification/results.json`, `verification/memory.json` and `verification/report.md` from a particular Actions run for its actual outcome.

Run after building the ISO:

```sh
python3 vm/verify.py --iso out/blue-mess-edition-VERSION-amd64.iso --output out/verification
```

The host needs Python 3.11 or newer, `qemu-system-x86_64`, `qemu-img`, and OVMF. The harness uses only Python's standard library. It selects a matching plain OVMF code/variable pair, copies the variables to a fresh writable file, and creates a new disposable 12 GiB qcow2 disk. It never attaches host block devices. An existing verification working directory is rejected to prevent accidentally reusing an old installation.

## Reference configuration

| Component | Setting |
| --- | --- |
| Architecture | amd64 |
| Guest RAM | 1 GiB |
| vCPUs | 2, qemu64 |
| Machine | pc-q35-8.2 |
| Acceleration | TCG software emulation |
| Graphics | QEMU std VGA, real guest Xorg |
| Resolution | 1024 × 768 |
| Firmware | OVMF UEFI, Secure Boot disabled |
| Disk | fresh 12 GiB virtio qcow2, GPT, EFI System Partition and ext4 root |
| Networking | no NIC while installing; virtio user network for installed boots |
| Desktop | normal-user Openbox, XFCE panel/power manager, authentication agent, one idle xterm running BusyBox ash |
| Other activity | default delivered services; no browser or extra interactive application |
| Swap use | exactly zero |
| Settling | 60 seconds after desktop and networking checks on each boot |
| Repetitions | three fresh installed-system boots |

QEMU's version and full invocation are captured alongside the result. Every boot retains the same installed disk and writable UEFI variables. The installed boots have neither the ISO nor fixture media attached. The host interacts through the emulated serial console and QMP keyboard; no verification service, account, credential or automatic login is injected into the distributed image. A random test-only account password is supplied to the real installer through a private file in the live environment's `/run`.

Before installation, the harness boots the identical ISO bytes through QEMU xHCI USB mass-storage with no NIC, authenticates the live root console, checks native OpenRC PID 1 and the mounted offline payload, discovers the USB backing disk from the actual media mount, and verifies `bme-install --dry-run --disk` rejects that disk. It records the USB console screenshot, media ancestry, rejection output, and an unchanged disposable-target partition header. It then shuts down and boots the same ISO as optical media for the actual installation, retaining the disposable disk and UEFI variables.

The harness authenticates through the real ttyS0 login and checks the user enters ash. It authenticates the same user on tty1 through the emulated keyboard, runs `bluemess-desktop start` initially and enables tty1 auto-start for the benchmark reboots, checks Xorg and Openbox run under that user's UID, and opens one xterm through the desktop's keyboard shortcut. `xrandr` selects and records the reference resolution on the real VGA display. The delivered panel, power manager, UPower and disabled idle display blanking are checked on every measured boot. Initial verification also checks desktop logout cleanup, C/Lua execution and a build against the running kernel headers. A QMP screenshot and Xorg logs preserve evidence of the guest desktop. Xvfb is not used.

The initial installed boot also checks DHCP, DNS, required packages, persistent APT settings, fresh visible home entries, `/bin/sh` and Bash compatibility, UUID-based mounts and the actual PID 1. A real package is installed and removed, APT checks dependency consistency, and an upgrade simulation is checked for attempts to replace the selected init. The benchmark then measures three reboots, so package-manager workload is not mixed into the fresh desktop measurement. Reboot and final poweroff use native `openrc-shutdown`.

## Metric and acceptance

For each boot the unmodified `/proc/meminfo` is preserved as `meminfo-boot-N.txt`:

```text
used_MiB = (MemTotal_kib - MemAvailable_kib) / 1024
```

Acceptance requires every unrounded value to be at most 350 MiB and `SwapTotal - SwapFree` to equal zero. The report lists all raw readings and the minimum–maximum range. A single failing boot fails the entire verification. The parser has explicit tests for the exact threshold, a one-KiB excess, swap use, malformed input, and a failed boot hidden by an average.

No cache dropping, swapping out idle services, temporary service suppression, or alternate metric is permitted. The ordinary serial administration shell remains present during measurement and its memory is included. After the reading the harness records OpenRC service status, the process list, kernel slab statistics, and per-process PSS from `smaps_rollup`. PSS assists attribution but does not account for all kernel memory.

If a reading exceeds the threshold, the raw result remains in the artifact and release validation fails. Compare the RSS/PSS and slab diagnostics before making an optimization, then rebuild and repeat the complete test. Preserve earlier failed run artifacts rather than editing their readings.

## Installer memory

`installer-meminfo.txt` is a separate raw reading after the live installer reaches its authenticated console. The installer runs with 1 GiB in this reference test and may need more memory than the installed desktop, particularly during payload decompression and initramfs generation. This reading is not a peak measurement and establishes no minimum memory requirement. The 350 MiB acceptance target describes measured installed desktop use, not a supported physical-RAM minimum.

## Failure evidence

Serial transcripts, QEMU invocations, installer output, partition facts, process/service/Xorg logs, screenshots, exact memory readings, a machine-readable outcome and a readable report are retained even when an assertion fails. A failure before measurement produces an empty `memory.json` readings array and an explicit failure; it never substitutes a predicted memory value. Diagnostic artifacts are candidate evidence, not validated download claims.
