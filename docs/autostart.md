# Commands once per boot

`bme-autostart` is one native system OpenRC service. It runs configured commands
during boot without an interactive login or `rc-service --user`. It is enabled
on installed targets, including when upgrading an older Blue Mess installation.
The live installer does not enable it. All command directories/user lists are
empty by default, so installing this feature runs no custom commands.

| Location | Trigger | Runs as |
| --- | --- | --- |
| `/etc/blue-mess/autostart.d/*.sh` | System boot | Root |
| `~/.config/blue-mess/boot.d/*.sh` | System boot, for accounts listed in `/etc/blue-mess/autostart-users` | That ordinary user |
| `${XDG_CONFIG_HOME:-$HOME/.config}/blue-mess/autostart.d/*.sh` | First Blue Mess desktop start in the boot | Logged-in desktop user |

Only executable `.sh` files run, in bytewise filename order. Use names such as
`10-prepare.sh` and `20-start.sh`, containing only letters, digits, dots, hyphens
and underscores. Each file executes its own shebang, with standard input closed.
Scripts should not ask for passwords or other input. Independent scripts continue
after a failure. Root scripts, their directory and the user list must be
root-owned, not symlinks, and not writable by group or others.

## Ordinary-user commands without login

As the ordinary user, create a boot script:

```sh
mkdir -p "$HOME/.config/blue-mess/boot.d"
cat > "$HOME/.config/blue-mess/boot.d/10-example.sh" <<'EOF'
#!/usr/bin/ash
set -eu
printf 'Started at boot: %s\n' "$(date -u)" >> "$HOME/.local/state/blue-mess/boot-example.log"
# Add your noninteractive commands here, using absolute executable paths.
EOF
chmod 755 "$HOME/.config/blue-mess/boot.d/10-example.sh"
```

Then run `sudo nano /etc/blue-mess/autostart-users` and add the exact account name
on its own line. Blank lines and lines beginning with `#` are ignored; inline
comments and surrounding whitespace are not accepted. Only ordinary accounts
with UID >= 1000, excluding nobody (65534), are accepted. Do not list root.

On the next boot, the service uses `runuser` to change UID, primary group and
supplementary groups before the runner accesses that user's home or scripts.
Boot commands run in the account's home directory with a clean environment:
`HOME`, `USER`, `LOGNAME`, `SHELL=/usr/bin/ash`, a standard executable search path,
the timeout and `LC_ALL=C`. Profiles are not sourced. There is no graphical
display, session D-Bus or promised elogind runtime directory. The boot path uses
the default `~/.config` and `~/.local/state`, independently of later desktop XDG
customizations. A home directory must already be mounted and accessible at boot;
a home unlocked only at login cannot supply boot scripts.

To try that user's boot scripts now, run `bluemess-autostart boot` as that user.
This counts as their attempt for the current boot. No sudo is needed for this
manual per-user invocation.

## Root commands

Place administrator-owned executable scripts in `/etc/blue-mess/autostart.d/`.
They run with `/` as the working directory. Use root only for commands requiring
root privileges; never source a user's home scripts from a root hook.

The service needs `bme-boot` and is ordered after enabled D-Bus, elogind, network
and logging services, and before greetd/SDDM and the configured console gettys.
This ordering does not guarantee
Internet connectivity. Commands needing a particular server or device should
check readiness with a bounded wait themselves.

## Desktop commands

Put desktop-dependent scripts in `~/.config/blue-mess/autostart.d/` instead.
The shared session launcher invokes them as the authenticated user after
starting Openbox, with X11 and its private session D-Bus available. This covers
tuigreet, agetty/startx and SDDM. The hook runs alongside Openbox startup, so a
script requiring a fully ready window manager or audio server should check that
dependency itself. It does not run for console-only or SSH logins.

The boot and desktop directories are separate scopes. A command placed in both
can run twice. The existing audio, panel, network and other managed components
keep their current startup owners; do not also add them here.

## Attempt records, limits and diagnostics

The Linux boot ID and a per-scope lock prevent duplicate automatic execution.
Each script is marked **started before it executes**, then its exit status is
recorded. There is at most one automatic attempt per filename per boot, including
failed or interrupted attempts. This does not guarantee that every command
finishes successfully: a power loss or interruption can leave partial effects.
Write scripts to tolerate interruption and review results before forcing a retry.

Logging out, starting a new terminal, restarting the service, or editing an
already-attempted script does not reset its record. A new filename is a new job.
Persistent user records survive full logout and runtime-directory removal. The
next kernel boot ID permits another attempt. Desktop applications that exit will
therefore not be relaunched automatically on another login in the same boot.

Each foreground script has a default 30-second limit. Timeout sends TERM,
followed by KILL after another five seconds if needed. `/etc/conf.d/bme-autostart`
sets `autostart_timeout` (1..300 seconds) for the system service and its user jobs.
For manual or desktop invocation, set `BME_AUTOSTART_TIMEOUT` in that environment.
Multiple scripts run sequentially, so their bounded durations add up. No desktop
script blocks Openbox startup. Logout terminates an active desktop hook and its
foreground command; the incomplete attempt remains recorded.

This is a startup runner, not a supervisor. Long-running foreground commands will
time out. A command designed to daemonize may return while leaving its process
running, but the runner provides no crash recovery or lifetime guarantee for it.
Use a dedicated service when restart or stop management is required. Stopping
`bme-autostart` neither clears records nor stops previously launched programs.

```sh
bluemess-autostart status             # this user's boot and desktop jobs
sudo bluemess-autostart status        # root jobs and configured users' jobs
sudo rc-service bme-autostart status  # OpenRC wrapper state
sudo rc-service bme-autostart start   # start the wrapper if it is stopped
sudo bluemess-autostart boot          # attempt jobs not yet attempted this boot
bluemess-autostart boot --force       # explicitly retry all your boot jobs
bluemess-autostart desktop --force    # retry desktop jobs from inside the desktop
sudo bluemess-autostart boot --force  # retry root and all configured user boot jobs
```

`--force` repeats successful jobs too; review scripts before using it. Ordinary
runner exits/status return nonzero for failed, incomplete or pending jobs. An
already-active runner returns nonzero rather than claiming completion. An empty
directory succeeds. OpenRC service state is not a substitute for per-job status.

System records/logs are in `/var/lib/blue-mess/autostart/system/`. User records/logs
are under `${XDG_STATE_HOME:-$HOME/.local/state}/blue-mess/autostart/`, in separate
`boot/` and `desktop/` directories. Each job has a `.state` and `.log` file; its
previous log is retained as `.log.old`. Logs are rotated per attempt, not by size.
Exit 124 normally indicates a timeout; interrupted attempts can remain `started`.

Remove execute permission to disable an individual script. Remove an account
from `autostart-users` to disable automatic boot execution for that user. To
disable the boot service, run `sudo rc-update del bme-autostart default`; restore
it with `sudo rc-update add bme-autostart default`. Upgrades preserve this choice
after the initial integration, using `/var/lib/blue-mess/autostart-integrated`.
Package upgrades do not execute the scripts. User scripts and logs are retained,
and Debian conffile handling preserves the user list and timeout configuration.
