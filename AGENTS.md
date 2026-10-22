# Blue Mess Edition constraints

- Target is Debian Sid amd64, native openrc-init PID 1, OpenRC services, Xorg/Openbox and BusyBox ash. Keep Debian Bash/dash and /bin/sh -> dash.
- Target shell programs use portable POSIX constructs supported by BusyBox ash. No Bash arrays or process substitution. Host build scripts may use Bash.
- Install only from the pinned Sid snapshot, with signature verification and no recommends/suggests. Refresh build/inputs.env deliberately and repeat the full VM suite.
- Never test destructive installer operations on host disks. Use only vm/verify.py-created disposable QEMU disks; installation runs without a network device.
- Do not claim ISO boot, installation, desktop or RAM success without an actual run. Failed candidates are not validated downloads. Never change memory metric or disable normal services during measurement.
- Debian native openrc-run services must not contain LSB INIT INFO headers: Debian dispatches those through its compatibility path. Put insserv metadata in /etc/insserv/overrides.
- Preserve package maintainer service-management behavior; each daemon has one startup owner. Do not add permanent CI hooks, accounts or credentials to target payload.
- Build/test: source build/inputs.env; docker build --build-arg DEBIAN_SNAPSHOT="$DEBIAN_SNAPSHOT" -t bme-builder -f build/Dockerfile .
- Static tests: docker run --rm -v "$PWD:/src" bme-builder build/check.sh
- ISO: docker run --rm --privileged -e VERSION=0.1.0-dev -e SOURCE_COMMIT="$(git rev-parse HEAD)" -v "$PWD:/src" bme-builder build/build.sh
- End-to-end: docker run --rm --privileged -v "$PWD:/src" bme-builder -c 'python3 vm/verify.py --iso out/blue-mess-edition-0.1.0-dev-amd64.iso --output out/verification'
- Completion record: docs/status.md. Keep unresolved blockers and actual test outcomes visible.
