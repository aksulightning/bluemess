# tuigreet-bme

The binary Debian package is `tuigreet-bme`; the command remains
`/usr/bin/tuigreet`, so greetd configuration and the login-manager switcher
continue to work. It Provides `tuigreet (= 0.9.1-6+bme1)` and Conflicts/Replaces
`tuigreet`. Installing it explicitly through APT replaces Debian's binary;
the two must not own the same files simultaneously. greetd itself is unchanged.

## Source and fix

`build/inputs.env` pins Debian source `tuigreet=0.9.1-6` from the existing
20261021T000000Z Sid snapshot. The local version is `0.9.1-6+bme1`.
The source package name remains `tuigreet` to retain Debian's dh-cargo rules.
Source hashes and build dependencies are verified by APT against the signed
snapshot index; there are no unpinned Cargo downloads or new Sid repositories.

`packages/tuigreet-bme/start-events-after-terminal.patch` adapts upstream
[3e18bcb7b68dfe5b8491ad08d5fbcbb326849a4f](https://github.com/tuigreet/tuigreet/commit/3e18bcb7b68dfe5b8491ad08d5fbcbb326849a4f)
to the 0.9.1 code. Creating the event channel remains early, but starting the
terminal input task moves after raw mode, Terminal::new and terminal.clear.
This addresses the startup race described in
[Debian #1153617](https://bugs.debian.org/1153617). It does not modify NVIDIA,
PAM, Xorg permissions, or add retry/sleep workarounds.
A companion local patch clears the screen directly with crossterm on exit
instead of constructing another Terminal while the event reader is still alive.

## Build and install

Build the documented builder, then run:

```sh
docker run --rm -v "$PWD:/src" bme-builder packages/tuigreet-bme/build.sh /src/out/tuigreet-bme
```

The build runs Debian's build checks and a five-run PTY test of the actual
packaged executable, including delayed cursor replies, rendered UI, and
keyboard/session IPC with a fake server and clean exit without another cursor query. No real credentials are used.
The package, corresponding source, build information and checksums are saved
in the Actions artifact with SHA256SUMS. ISO artifacts and rolling releases
include the same package/source directory in tuigreet-bme.tar.xz with its own
tuigreet-bme.sha256 checksum, preserving source paths when downloaded. The ISO build installs it in the target only, before
bme-config and greeter configuration. The source is included with published
artifacts; upstream and Debian copyright/license files remain in the package.

On an existing Blue Mess installation, download the artifact and verify its
SHA256SUMS, then install the exact package from a recovery TTY:

```sh
sudo apt install ./tuigreet-bme_0.9.1-6+bme1_amd64.deb
```

Reboot when ready. Keep tty2/tty3 available. A passing PTY test is not evidence
of a successful VT boot, PAM login, Openbox session or NVIDIA hardware test.
Run `vm/verify.py --greeters-only` and repeat cold boots and logout/login on
the affected NVIDIA machine before treating the image as hardware-validated.

To return to a future corrected official package, inspect `apt policy tuigreet`
and explicitly run `sudo apt install tuigreet tuigreet-bme-`. Review APT's
transaction first. Do not enable unrelated Debian suites to satisfy dependencies.
