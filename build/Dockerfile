# The container is a build host only. Target package inputs are snapshot-pinned.
FROM debian:trixie-slim
ARG DEBIAN_SNAPSHOT=20261021T000000Z
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
    rm -f /etc/apt/sources.list.d/* && \
    printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s/ sid main non-free-firmware\n' "$DEBIAN_SNAPSHOT" > /etc/apt/sources.list && \
    printf 'APT::Install-Recommends "false";\nAPT::Install-Suggests "false";\n' > /etc/apt/apt.conf.d/99bme && \
    apt-get update && apt-get install -y ca-certificates debian-archive-keyring mmdebstrap \
      squashfs-tools xorriso mtools dosfstools grub-efi-amd64-bin grub-common \
      gdisk zstd python3 python3-pexpect qemu-system-x86 qemu-utils ovmf \
      busybox shellcheck git && rm -rf /var/lib/apt/lists/*
WORKDIR /src
ENTRYPOINT ["/bin/bash"]
