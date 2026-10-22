# Building and provenance

The supported delivery path is `.github/workflows/iso.yml`, on GitHub-hosted
`ubuntu-24.04`. It builds both roots inside `build/Dockerfile`, captures the
container image identity and complete build-tool package versions, then uses
mmdebstrap minbase (essential packages and APT, without an init metapackage).
Target packages come only from signed Debian Sid snapshot repositories. Each
root explicitly selects openrc-init and openrc, preserves init-system-helpers,
and pins competing init providers out. No repository trust bypass is used.
`check-valid-until=no` is necessary for archived snapshot metadata; signature
verification remains enabled. The build host's initial Debian container is
separate from both delivered roots; its packages never become payload files.

`manifests/target.txt` and `manifests/installer.txt` list selected packages.
Debian dependencies are resolved from the same snapshot, and the resulting
complete package/version/architecture manifests accompany every image. The
build records source commit, snapshot, repository source, tool versions, image
identity and build time. This provides provenance, not a claim of bit-identical
reproducibility. To refresh inputs, update `build/inputs.env` and deliberately refresh the official
Debian base-image digest in `build/Dockerfile` when needed, inspect the package
resolution and integration changes, and pass the complete VM/benchmark suite.

For a local build on a disposable Linux development machine with Docker:

```sh
source build/inputs.env
docker build --build-arg DEBIAN_SNAPSHOT="$DEBIAN_SNAPSHOT" -t bme-builder -f build/Dockerfile .
docker run --rm -v "$PWD:/src" bme-builder build/check.sh
docker run --rm --privileged -e VERSION=0.1.0-dev -e SOURCE_COMMIT="$(git rev-parse HEAD)" -v "$PWD:/src" bme-builder build/build.sh
docker run --rm --privileged -v "$PWD:/src" bme-builder -c 'python3 vm/verify.py --iso out/blue-mess-edition-0.1.0-dev-amd64.iso --output out/verification'
python3 build/validate-results.py out
```

The privileged build container requires real chroot and mount support. It never
accepts a host block device. VM tests create their own disposable image. Never
pass host devices to this container. `work/` holds roots and temporary images;
`out/` holds artifacts and logs. Delete `work/` before a new build: roots are
intentionally not reused. Neither directory is committed.

ISO assembly uses Debian live-boot, an xz squashfs installer root, and a separate
zstd tar payload. Debian grub-mkrescue creates the EFI El Torito/hybrid image;
its actual layout report is retained. It contains all target packages,
initramfs tools and GRUB modules needed to install without a connection.

The release job runs only on existing `v*` push tags, after verification. It
downloads the validated artifact, verifies the ISO checksum again, and publishes
those bytes. It refuses an existing release rather than replacing its assets.
Only that job has `contents: write`. Ordinary jobs have `contents: read` and
never use `pull_request_target`. Official actions are pinned to full commit SHAs
resolved from their upstream tag refs at implementation time.
