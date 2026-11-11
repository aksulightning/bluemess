#!/bin/bash
# Run in the snapshot-pinned builder, never on the installed target.
set -euo pipefail
cd "$(dirname "$0")/../.."
source build/inputs.env
output=$(realpath -m "${1:?usage: build.sh OUTPUT}")
mkdir -p "$output"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
repo=$PWD
cd "$stage"
# APT verifies source hashes against the signed snapshot Sources index.
apt-get update
apt-get source "tuigreet=$TUIGREET_SOURCE_VERSION"
cd tuigreet-0.9.1
patch --batch --fuzz=0 -p1 < "$repo/packages/tuigreet-bme/start-events-after-terminal.patch"
patch --batch --fuzz=0 -p1 < "$repo/packages/tuigreet-bme/clear-without-cursor-query.patch"
python3 "$repo/packages/tuigreet-bme/prepare.py" "$TUIGREET_BME_VERSION"
# Record the backport as a quilt patch so the published source is rebuildable.
EDITOR=true dpkg-source --commit . bme-terminal-initialization.patch
dpkg-buildpackage -us -uc
dpkg-deb -x "../tuigreet-bme_${TUIGREET_BME_VERSION}_amd64.deb" "$stage/check-root"
python3 "$repo/packages/tuigreet-bme/check-pty.py" "$stage/check-root/usr/bin/tuigreet"
cd ..
cp tuigreet-bme*.deb "$output/"
mkdir -p "$output/source"
cp ./*.dsc ./*.tar.* ./*.buildinfo ./*.changes "$output/source/"
(cd "$output" && sha256sum ./*.deb source/* > SHA256SUMS)
dpkg-deb -f "$output/tuigreet-bme_${TUIGREET_BME_VERSION}_amd64.deb" Package Version Depends Provides Conflicts Replaces
