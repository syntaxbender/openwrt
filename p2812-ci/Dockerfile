FROM --platform=linux/amd64 debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates file gawk gettext git libncurses-dev \
    libssl-dev patch perl python3 python3-setuptools rsync unzip wget zstd && \
    dpkg-query -W > /usr/local/share/p2812-host-packages.txt && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /work
