# Implementation record

## 2026-11-09: bounded greeter startup readiness and settling delay

- Native OpenRC greetd startup now waits at most 15 seconds for an accessible
  tty1 and a successful elogind D-Bus ping. Each ping has a one-second reply
  timeout; BusyBox timeout bounds the complete wait. Changed failure reasons
  are logged without repeating the same message on every probe.
- Added `/etc/conf.d/greetd` as a Debian conffile with a three-second settling
  delay, configurable from 0 to 30 seconds. Invalid settings fail before
  startup. Added the explicit dbus-bin dependency and required timeout applet.
- Existing two-second/five-per-minute OpenRC crash recovery remains intact.
  The readiness hook runs only on start or explicit restart, not on daemon
  respawns or login/logout. No periodic health checker or upgrade-time restart
  is added. The clock workaround and local greetd TOML settings are preserved.
- All 64 local tests passed under dash, including 11 new readiness/start-hook
  tests and a real 15-second outer-deadline test using host GNU timeout.
  Shell/Python syntax, new VM shell snippets, Debian package assembly,
  packaged helper permissions/content and conffile registration passed.
- The disposable-QEMU suite now checks explicit greetd restart and daemon
  crash recovery before login, and verifies that the daemon stays unchanged
  through desktop checks. Existing login/logout and three-boot checks remain.
  Docker, QEMU, BusyBox and ShellCheck are unavailable locally; the full static
  target checks, ISO/VM suite and physical-console validation remain pending.
  A startup race is still a hypothesis; this is not a verified display fix.

## 2026-11-09: terminal paste and F10 defaults

- Disabled XFCE Terminal's unsafe-paste dialog and menu shortcut key through
  its Xfconf preferences, so F10 is available to terminal applications.
- Added defaults for new users and users without terminal settings. Existing
  Xfconf files are preserved; legacy terminalrc files are left for Terminal's
  own migration. README commands apply only these two preferences explicitly.
- XML preferences, shell syntax, package contents, new-setting seeding and
  existing/legacy configuration preservation checks passed. Interactive paste
  and htop keyboard handling have not been tested locally.

## 2026-11-09: XFCE Terminal as the default

- Added xfce4-terminal alongside the retained xterm fallback. New images select
  its Debian x-terminal-emulator wrapper; new user defaults select it in XFCE,
  the panel launcher, Openbox shortcuts and terminal application menu entries.
  Shell launchers continue to run BusyBox ash as a login shell.
- Existing user configuration is preserved, with adoption steps in the README.
  Missing XFCE helper preferences are seeded at desktop startup.
- Updated VM terminal process/window discovery and benchmark documentation to
  exercise the delivered default terminal without changing the memory gate.
- All 53 existing tests passed under dash. Shell/Python syntax, skeleton XML,
  package assembly and packaged terminal-default checks passed. Graphical
  operation and ISO/VM validation have not been run; BusyBox and ShellCheck
  are unavailable locally.

## 2026-11-09: text-only APP MENU and panel ordering

- Added Whisker Menu as the first item on the bottom panel, with the exact
  title APP MENU and its button icon disabled. It opens All Applications.
  Window Buttons is last; other existing items retain their relative order
  and configuration.
- Added xfce4-whiskermenu-plugin to the target manifest. Its native title-only
  button setting avoids the built-in Applications Menu's always-visible icon.
  The pinned snapshot and session manager configuration are unchanged.
- Existing user layouts remain intact; the README documents adding the menu
  interactively. New users and users without panel settings get the default.
- XML parsing, plugin-ID consistency, existing-item preservation and packaged
  configuration checks passed. Interactive menu opening and application launch
  have not been exercised locally.

## 2026-11-09: keep tuigreet output updating while idle

- Enabled tuigreet's built-in clock with an explicit seconds format in the
  packaged greetd configuration. The existing render timer now has changing
  visible content every second, without synthetic login input or a new daemon.
- Upstream tuigreet 0.9.1 already schedules rendering twice per second;
  this change enables changing output, not an additional refresh timer or
  forced full-screen repaint. Hardware effectiveness remains unverified.
- Added instructions for updating existing installations whose local conffile
  is preserved on package upgrades. No private diagnostic logs were included.
- TOML parsing, command argument checks and package-content verification passed.
  Physical-console testing is still required before claiming the display
  problem is resolved.

## 2026-11-09: GPU installation preparation helper

- Added `bluemess-prepare-gpu-install` to the bme-config package. It asks for
  NVIDIA or AMD and confirmation that system updates have been installed,
  requires root on amd64, checks package state and prevents concurrent runs.
- NVIDIA preparation refuses existing APT-managed NVIDIA packages, pins the
  NVIDIA package families across architectures, enables i386 and installs the
  requested build/GLVND dependencies plus headers for the running kernel.
  Only after those succeed does it disable Nouveau and rebuild initramfs.
  It requires a reboot before the user runs the vendor installer; it never
  downloads or starts a `.run` file or unloads the active graphics driver.
- AMD preparation installs Debian firmware, Mesa and the AMD Xorg driver
  through APT without adding NVIDIA pins or blacklists. Both paths refuse
  package removals and report initramfs failures without claiming success.
- Added usage, retry and undo documentation. Existing custom configuration
  is preserved, and no private user diagnostic logs were added.
- All 53 local tests passed under dash, including 17 GPU preparation tests
  with isolated command stubs and real APT policy parsing for amd64/i386.
  Shell syntax checks and Debian package assembly passed; the packaged helper
  matches the source and is executable. BusyBox, ShellCheck, Docker and QEMU
  are unavailable locally. Actual package installation, initramfs rebuilding,
  vendor driver installation and physical NVIDIA/AMD operation remain untested.

## 2026-11-09: archive the verified ISO workflow

- Moved `.github/workflows/iso.yml` unchanged to
  `.github/oldworkflows/iso.yml`, outside GitHub Actions workflow discovery.
- The untested ISO workflow and rolling release remain active. Static tests,
  VM verification and the memory gate remain available through the documented
  local commands, but no longer run automatically through the archived workflow.
- Verified that the archived file retains the original Git blob and that
  `build-iso.yml` is unchanged.

## 2026-11-09: rolling untested release

- Successful pushes or manual builds on main now replace the
  `untested-refreshing` prerelease and tag after verifying the ISO checksum.
  Feature/fix branches still upload untested Actions artifacts.
- The release job serializes replacement, skips superseded commits, and
  uploads the replacement as a draft before publishing. Only the fixed
  rolling tag/release is deleted; existing commit-tagged releases remain.
- YAML parsing and embedded Bash syntax passed. Seven mocked lifecycle
  scenarios passed: first publication, replacement, orphan tag, stale
  commit, API lookup failure, bad checksum, and upload failure.
- Hosted publication is pending. Replacement is not atomic: an upload
  failure after deletion can leave the release absent or in draft until
  rerun. The untested workflow still skips static/VM/RAM validation.
- Verified run 42569950677 failed the unchanged 350 MiB RAM gate; the
  separate untested run 42569950675 successfully uploaded its ISO artifact.

## 2026-11-08: three login VTs, diagnostics on tty4 and automatic PipeWire

- Installed tty1 uses greetd/tuigreet, tty2 and tty3 use agetty, and tty4
  is diagnostics only. The native getty refuses other numbered terminals.
  Serial recovery remains separate from the F-key console layout.
- Both Linux boot paths select tty4 as /dev/console. Kernel output stays
  there while the greeter selects tty1; userspace syslog and supervised
  daemon messages are mirrored to tty4 and retained in /var/log/messages.
  The live installer selects tty1 after startup without a tty4 getty.
- The target explicitly includes PipeWire, WirePlumber, PulseAudio/ALSA
  compatibility, UCM profiles, pavucontrol and Intel/SOF audio firmware.
  One user-session script owns startup, readiness, duplicate prevention,
  bounded process recovery, restart, diagnostics and playback testing.
  The desktop starts it automatically and stops it on logout.
- Added real subprocess lifecycle tests, root-layout/GRUB tests, QEMU HDA
  playback capture, real tty2/tty3 authentication and tty4 routing probes.
  Playback is checked initially and on all three benchmark boots; missing
  or silent playback blocks the validated artifact gate.
- All 36 local tests passed under dash, shell/Python syntax checks passed,
  and the bme-config Debian package assembled successfully. Docker, QEMU and BusyBox are unavailable locally;
  hosted validation results follow; physical playback remains untested.
- Hosted runs 42520020576 and 42519994212 passed the BusyBox checks, ISO
  assembly, USB boot, offline installation, tty1/2/3 password login and tty4
  routing. Automatic PipeWire startup, crash recovery, explicit restart,
  captured non-silent HDA playback and desktop logout cleanup passed.
- Run 42519994212 also captured non-silent playback after two reboots. Idle
  memory was 357.04 and 350.73 MiB, above the unchanged 350 MiB limit.
  Both runs eventually hit the intermittent terminal-shortcut launch timeout.
  These candidates are not validated releases.
- Follow-up removes ten unnecessary persistent logging shells using exec and
  the existing BusyBox logger. The VM shortcut probe paces individual PS/2 key
  transitions and releases modifiers explicitly; this still exercises the real
  Openbox binding. New runs must establish whether it resolves the timeout.
  Failure diagnostics now include tty4. Full acceptance remains pending.

## 2026-11-08: greetd and tuigreet on installed tty1

- The pinned Debian Sid snapshot provides greetd 0.10.3-7 and tuigreet
  0.9.1-6. Installed-system tty1 now uses native OpenRC greetd with Debian
  PAM. Tuigreet opens an interactive ash login shell, which runs the
  existing per-user desktop auto-start hook.
- tty2 and the serial console use agetty. The live installer retains
  agetty on tty1. Upgrading `bme-config` with both greeter packages
  installed changes the next boot's runlevel links for older installations.
- Package assembly, runlevel fixtures, syntax checks and all 26 local
  tests passed. Hosted validation must exercise the real tuigreet password
  prompt, active seat and runtime directory, desktop startup and return
  to the greeter on logout.

## 2026-11-08: session checks at desktop startup

- Added `bluemess-session-check` for the active local tty1 session, elogind
  runtime directory, session D-Bus, and graphics and audio device access.
  It also reports X11 and PulseAudio sockets and dconf runtime access.
- Manual and automatic desktop starts record a pre-Xorg report. The
  packaged Openbox session records a second report after D-Bus starts.
  Both stages let startup proceed when the check finds a problem.
- All 26 local tests and the package build passed. Nine simulated cases
  covered healthy sessions and failures. The VM verifier checks that both
  reports ran. Hosted VM validation is pending.

## 2026-11-08: local seat and device permissions

- Removed the native udev service's `--resolve-names=never` option so the
  Debian rules can assign named groups to device nodes. Earlier NVIDIA logs
  showed denied access to a render node left at `root:root`.
- The installed VM suite now checks that input event devices have the
  `input` group and that the active tty1 login belongs to `seat0`.
  Local package assembly, shell syntax, and all 25 local tests passed.
  The new VM checks and physical device behavior still need verification.

## 2026-11-08: Openbox audio commands

- `bluemess-start-audio` uses the validated session runtime directory for
  both sockets, waits for PipeWire before starting its clients, and reports
  an already responding PulseAudio server. The previous launcher name is
  available as an alias.
- `bluemess-fix-audio` lists ALSA cards and server profiles or changes the
  profile of a named card. `bluemess-audio-panel` uses its server discovery
  to open `pavucontrol` against a responding socket.
- All 25 local tests passed. Simulated audio processes verified server
  discovery, profile commands, panel handoff, socket paths, startup order,
  and cleanup. The package build included all three commands and the alias.
  Playback through the new commands still needs hardware verification.
- A user trace showed that an Openbox terminal had a valid runtime directory
  but lacked a session D-Bus address. The audio launcher now starts a private
  bus in that case. Simulated checks covered missing and inherited addresses,
  an already running audio server, and cleanup on Ctrl+C.

## 2026-11-08: NVIDIA and Openbox audio troubleshooting

- On the reported RTX 3060 installation, DKMS matched the running kernel,
  `nvidia-smi` detected the GPU, and Xorg received the primary DRM device
  from elogind. The desktop user was denied access to the root-owned
  `renderD128` node. The troubleshooting guide records a temporary permission
  test, a local udev repair, and a separate X11 socket ownership repair.
- The user confirmed that manual PipeWire startup worked once the server was
  running before its clients. The optional `bluemess-audio-start` launcher
  waits for the PipeWire core and runs the three audio processes in the
  foreground Openbox terminal session. Audio packages are installed separately.
- All 25 local tests passed. A local package build included the executable
  launcher. Simulated audio processes verified startup order, duplicate
  prevention, and cleanup on interruption and process failure. Hardware
  playback through the new launcher has yet to be verified.
- A follow-up handles an unusable inherited `XDG_RUNTIME_DIR` by checking the
  existing elogind login directory. Eight simulated cases covered configured
  paths, fallback, and failure when neither directory is usable.

## 2026-11-08: commit-tagged ISO prereleases

- In [push run 40074552091](https://github.com/aksulightning/bluemess/actions/runs/40074552091),
  ISO assembly, VM verification and the release-job checksum passed. The
  release step then reported an HTTP 404 from GitHub CLI. The old script
  attempted to delete the previous alpha before staging its replacement.
- Feature branch pushes now use separate full-SHA prerelease tags ending in
  `-iso-tested` and `-iso-untested`. The tested release requires all acceptance
  gates. The untested release requires successful assembly and a matching
  checksum. Publication uses each workflow's own artifact and retains older
  published releases.

## 2026-10-24: add independent, untested ISO build

- Added a separate `.github/workflows/build-iso.yml` on branch pushes and
  manual dispatch (after merge to the default branch). It runs the pinned
  builder and ISO assembly, bypassing static checks, QEMU verification,
  the memory gate, and release publication. It does not depend on results
  of the existing verified workflow.
- A successfully assembled ISO is uploaded with an unmistakable
  `-UNTESTED` artifact name together with the checksum and build records.
  If image assembly itself fails, only the available diagnostics are kept.
  The original `iso.yml` acceptance and release requirements stay intact.
- The workflow has not yet been exercised by a hosted run. A build-only
  artifact is not evidence of a bootable or installable ISO.

## 2026-10-24: align publication-gate fixtures with 350 MiB

- The static validation step failed after the memory-limit update because
  tests/test_delivery.py still treated 300 MiB plus one KiB as over budget.
  Under the new 350 MiB threshold that reading is correctly accepted, so the
  negative test was obsolete; the release validator itself remains unchanged.
- The publication-gate fixtures now derive the exact boundary from the shared
  MEMORY_LIMIT_MIB setting, and assert rejection for one KiB above it, a
  single failing boot among three, missing readings, and swap usage.
  The accepted fixture exercises the inclusive limit.
- Full hosted CI and VM acceptance for the corrected commit are still pending.

## 2026-10-24: desktop idle memory acceptance raised to 350 MiB

- The preceding candidate (commit 6b5f5c5d76aec239bf460ffae0d94c1d68e07b7f,
  run 40027402814) passed USB and installed-disk boot, offline installation,
  networking/package checks, the complete desktop interaction and developer
  toolchain checks, logout, auto-start and three fresh benchmark boots.
  Its three unrounded desktop readings were 324.76171875, 327.05078125 and
  316.38671875 MiB, all with zero swap, so the 300 MiB gate failed.
- The new acceptance budget is 350 MiB for *each* fresh installed desktop
  boot. The original /proc/meminfo metric, 1 GiB reference guest, default
  services, 60-second settling period, three boots, zero-swap requirement and
  fail-closed publication behavior are unchanged. This changes the acceptance
  requirement, not the measured memory consumption.
- Boundary tests cover exactly 350 MiB, one KiB above it, a 325 MiB reading
  and zero-swap enforcement. The preceding run remains failed under its
  original 300 MiB requirement; it is not retroactively validated. A fresh
  full Actions run and successful artifact publication remain unverified.

## 2026-10-23: optional tty1 desktop startup and development tools

- Added user commands for persistent tty1 auto-start, status and manual desktop
  startup, with non-root/tty/display guards and default false. No autologin or
  automatic logout is introduced. Existing accounts can opt in via the packaged
  user-profile hook and session helper without replacing their own profiles.
- The Blue Mess session runs Openbox, one bottom XFCE panel, power manager and
  lxpolkit in one private D-Bus session. Companion processes stop on logout.
  Missing XFCE user settings are seeded without overwriting existing choices.
- Default idle sleep, blanking, dimming and locking are disabled. elogind handles
  lid suspend, and critical power requests PowerOff. UPower/polkit retain their
  packaged D-Bus activation. Physical battery/lid behavior is untested.
- Added build-essential, linux-headers-amd64, DKMS and Lua 5.4 to the target.
  Python is retained: the exact snapshot's openbox package directly depends on
  python3. Removing it would break Debian package dependencies.
- Focused local command/guard tests and syntax/XML checks precede the hosted
  offline installation/desktop suite. VM checks cover panel/power presence,
  logout cleanup, matching-header module compilation, C/Lua and auto-start on
  three reboots. The full delivered desktop retains the 300 MiB/zero-swap gate.
- All 24 local tests passed under dash; desktop shell/XML syntax and embedded
  verifier shell snippets passed. bme-config assembled successfully with a
  workspace TMPDIR. BusyBox ash, real window drag/keyboard resize, runtime and
  memory acceptance for this change remain pending the hosted run.

## 2026-10-23: restore Openbox window interactions

- The first alpha's custom Openbox configuration defined only the desktop
  right-click menu. Window move/resize, click-to-focus and titlebar button
  bindings were missing; starting Xorg/Openbox did not exercise these actions.
- Added titlebar drag, Alt-left drag, edge/corner resize, Alt-right drag,
  focus/raise, window menu, minimize/maximize/close and titlebar double-click.
  Alt+F7/Alt+F8 provide keyboard move/resize. The root menu is preserved.
- XML parsing and the focused binding configuration were checked locally.
  Interactive dragging has not been exercised locally; hosted VM acceptance
  still checks desktop startup, not a real mouse drag.
- Existing home directories retain their user configuration. The fix is in the
  packaged skeleton for new installations/accounts; an existing session can
  restore Debian's default rc.xml from /etc/xdg/openbox/rc.xml and reconfigure
  Openbox to recover working window controls immediately.

## 2026-10-23: first replaceable alpha release

- Push run 40001104011 and PR run 40001110594 completed successfully, including
  artifact finalization and validated ISO upload. The tag-only release job was
  skipped on those branch/PR events.
- Successful pushes to feat/blue-mess-edition now publish v0.1.0-alpha.1 as the
  first experimental prerelease. Only that named prerelease is replaceable:
  delete its release/tag, upload the new validated artifacts to a draft, then
  publish it as a prerelease. Existing non-prereleases are protected.
- Release notes identify its experimental status, supported hardware scope,
  destructive installation, mutable assets, source commit and validation run.
  Version-tag releases retain their existing no-overwrite policy.
- YAML and release-script Bash syntax were checked. Actual publication must be
  confirmed by the next successful push run and release asset list.

## 2026-10-23: artifact finalization permissions

- The 300 MiB candidate reached artifact finalization, where the host runner
  could not update out/build-metadata.json created by the root build container.
- Validation, checksum verification and diagnostic archive creation now run
  inside the same builder image as root. This also permits reading private
  diagnostic files while packaging, without broadening their permissions.
- The workflow change was checked for YAML and embedded Bash syntax. A fresh
  hosted run must confirm validated artifact upload before delivery is claimed.

## 2026-10-23: desktop acceptance budget changed to 300 MiB

- Run 39978729045 passed USB boot, offline installation, disk-only startup,
  networking/package checks, rootless Xorg/Openbox and three real reboots.
  It failed the original 150 MiB memory budget: 274.18359375, 275.203125 and
  260.01953125 MiB, with zero swap used on every boot.
- The approved desktop idle acceptance budget is now 300 MiB on every boot.
  This is a requirement change, not a reduction in measured memory use. The
  metric, reference VM, 60-second settling period, normal services, three boots
  and zero-swap requirement are unchanged. Historical results remain failed
  under their original 150 MiB requirement.
- The threshold is defined once in vm/benchmark.py and used by measurement,
  reporting and publication validation. Existing boundary tests are updated
  for exactly 300 MiB and one KiB over; documentation reflects the new budget.
- A fresh Actions run is required before a candidate receives validated status.

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

### First expanded desktop VM run

- Run 40022621472 built the ISO, completed the offline install and booted the
  installed system. Xorg, Openbox, the panel, power manager, lxpolkit, UPower and
  polkitd were present; the screenshot showed the configured bottom panel.
- Verification stopped waiting for xterm after the initial keyboard shortcut.
  Added a window-manager readiness check and bounded shortcut delivery retries,
  plus persistent desktop-session output and Xorg-log failure diagnostics.
  Desktop interaction, toolchain, auto-start and memory acceptance still need
  the corrected run; no new validated release is claimed.

- Login ordering review moved the guarded startup hook to the end of the user
  profile. Enabling auto-start appends the marked block once for older users;
  this preserves their settings and loads PATH/XDG configuration before X.

- Run 40024901777 passed panel/power-manager/UPower checks, disabled idle display
  blanking and terminal shortcut activation. The new mouse probe failed without
  moving the window. It mixed an Xlib pointer warp with emulated PS/2 events;
  the corrected probe uses XTEST for the entire pointer gesture on the real
  Xorg desktop, preserving active Openbox config and geometry on failure. It
  does not move windows through a window-manager API. Keyboard resize remains
  real QMP input. Subsequent logout/toolchain/auto-start/RAM checks are pending.

- Run 40026201436 confirmed real titlebar dragging: the xterm moved from
  (270, 219) to (318, 243). The keyboard resize probe sent only one arrow;
  upstream Openbox resize_with_keys uses that first arrow to select an edge,
  so the probe now sends a second arrow before confirming the changed width.
