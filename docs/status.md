# Implementation record

## 2026-10-23: installer mount correction (not VM-validated)

- Latest PR run 39808322031 successfully booted the live installer, then failed
  mounting /dev/vda2 immediately after successful ext4 formatting. The engine
  log reports a SquashFS superblock error; payload extraction never began.
- The installer now specifies ext4 for the root mount and vfat for the ESP.
  This removes automatic filesystem detection from the format/mount boundary.
  util-linux 2.42.4 can accept udev partition tags without a filesystem type
  instead of probing the newly formatted device; that mechanism is consistent
  with the failure, but the run did not capture the udev database to prove it.
- Only shell syntax and the focused diff were checked for this correction.
  Docker, QEMU and BusyBox are unavailable locally. A real offline VM install
  remains required; desktop and memory acceptance remain unmeasured.

## 2026-10-22

- Repository was empty. Initialized default branch with an explicit unvalidated
  status, then created `feat/blue-mess-edition` for implementation.
- Inspected Sid openrc/openrc-init 0.64.1-2 metadata and Debian packaging.
  Native init is supplied by openrc-init; Debian omits most upstream native
  boot services, requiring explicit integration. BusyBox does not provide ntpd
  in the selected build, so chrony is selected explicitly.
- Implemented separate snapshot-backed target/installer construction, packaged
  configuration, CLI installer, EFI hybrid ISO assembly, Actions validation and
  release gates, and actual QEMU installation/desktop/benchmark tooling.
- Local checks and remote run outcomes are recorded below when executed.
- No ISO, boot, install, or memory result is asserted before actual execution.

## Checks actually run locally

- 21 non-destructive Python tests passed, including installer syntax and
  behavior tests under Debian BusyBox ash 1.38.0.
- Installer ShellCheck 0.11.0 passed. Build scripts passed Bash syntax checks.
- bme-config Debian package assembled successfully with dpkg-deb.
- Local execution environment lacks a usable /proc and QEMU; no local boot or
  full ISO build result is claimed. Remote Actions is the intended execution path.

## Remote execution

- Draft PR: https://github.com/aksulightning/bluemess/pull/1
- Initial push run: https://github.com/aksulightning/bluemess/actions/runs/39798798781
- Its build job remained queued with no assigned runner and zero executed steps
  at the latest inspection. No ISO, checksum, VM or RAM result exists yet.
- Follow-up checks add hybrid USB boot smoke, original optical offline
  installation, complete installer-log extraction, publication byte identity,
  missing-artifact rejection, and package-maintainer service metadata.
- Local full builds cannot substitute: Docker and QEMU are unavailable and
  unshare fails because /proc/self/uid_map is unavailable in this workspace.

## First Actions build failure

- Initial push run completed with failure during candidate construction, exit
  141 after assembling the target root. The build environment, ash tests and
  diagnostic upload passed; ISO and VM steps did not complete.
- Removed early-exiting grep checks from pipefail pipelines (SIGPIPE risk),
  and added an ERR trap with exact build line/command reporting for subsequent
  failures. This correction still requires the next real build to validate it.

- Added ash defaults for both useradd and adduser, with guest assertions, so
  accounts created after installation follow the distribution shell policy.
- Corrected-build run: https://github.com/aksulightning/bluemess/actions/runs/39800208522
  remained queued with zero job steps and no runner at the subsequent inspection.

## First candidate and actual USB boot

- Corrected PR run 39800217819 successfully assembled an 842 MiB EFI/GPT
  hybrid candidate ISO. Its later VM step was cancelled by the next source push.
- Preserved USB serial evidence shows Linux booting native OpenRC 0.64.1 and
  passing root/local-filesystem startup, then failing bme-boot because
  dbus-uuidgen rejects a precreated empty machine-ID file. No login/installation
  or desktop acceptance is claimed for this candidate.
- Fixed boot to remove an empty ID before generating a fresh one. Added the
  mountkernfs compatibility provider and fail-fast boot assertions. Full
  installation and RAM results remain unmeasured until a corrected VM run.

- A later push run (39801581926) failed before construction because Docker Hub
  returned HTTP 500 while reading the Debian base manifest. Added three bounded
  container-build attempts, preserving each attempt's log.
- Native boot now runs the explicitly selected standalone sysusers/tmpfiles
  helpers, including the root-owned X11/ICE socket directories required by
  ordinary-user Xorg. Installer refreshes cached console keyboard settings
  before generating the target initramfs.

## Installation and disk-only boot verified

- Run 39802020950 built the corrected candidate, booted it as USB, and verified
  rejection of its own USB disk. The real CLI installer then completed onto a
  disposable disk with guest networking disabled.
- The installed disk booted without the ISO under native openrc-init. All
  expected OpenRC service state markers, serial ash/sudo login, exact fresh-home layout,
  UUID mounts, DHCP/DNS, persistent APT policy, actual package install/removal
  and an init-preserving upgrade simulation passed.
- Desktop validation stopped at the tty1 login assertion, before Xorg started;
  no desktop or memory result was measured. Adding native utmp initialization
  and direct session/process diagnostics instead of relying solely on who.
- Removing GRUB's unneeded HFS+/APM hybrid layout preserves EFI/GPT boot while
  avoiding extra filesystem probes. Earlier USB media write-error attribution
  to HFS+ is an inference; the rebuilt USB path must be tested again.

## Actual daemon/process verification

- Run 39804306807 repeated USB boot, offline installation and disk-only boot
  successfully with the simplified EFI/GPT layout. Real tty1 password login
  produced the expected tester-owned BusyBox ash process.
- The stronger logind assertion failed: process diagnostics showed dbus-daemon,
  elogind, chronyd and udevd absent despite their OpenRC state markers reporting
  started. The earlier state-only checks do not establish those daemons worked.
- Added actual executable/process and single-supervisor assertions plus a system
  D-Bus method call, and retained PAM/boot/system log diagnostics. Investigating
  the startup-state mismatch before any desktop or memory acceptance claim.

- Root cause confirmed in Debian's patched openrc-run: inline LSB headers route
  native services through a compatibility branch that skips their default
  daemon start functions. Moved those headers to insserv override files; native
  scripts now classify correctly. The build checks the actual Debian parser,
  Debian helper checksums, active elogind PAM configuration, and clean volatile
  directories before creating either root filesystem.

- Run 39806982630 built both images with correct native daemon dispatch, then
  exposed the Debian elogind executable at /usr/libexec/elogind (a file, not
  a directory). The incorrect command prevented gettys from starting. Corrected
  the path from the selected package contents and added build assertions for
  every declared native-service command in both roots. No desktop or RAM result
  is claimed for this failed candidate.
