# Implementation record

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
