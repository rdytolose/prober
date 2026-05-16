# Prober container: Python + sing-box (+ optional openvpn).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SINGBOX_VERSION=1.10.7

# System deps: curl + ca-certs + openvpn + microsocks (for openvpn fan-out).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl tar gzip iproute2 iputils-ping \
      openvpn microsocks \
 && rm -rf /var/lib/apt/lists/*

# Install sing-box from the official release tarball.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) sb_arch=amd64;; \
      arm64) sb_arch=arm64;; \
      armhf) sb_arch=armv7;; \
      *)    echo "unsupported arch $arch"; exit 1;; \
    esac; \
    curl -fsSL -o /tmp/singbox.tgz \
      "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-linux-${sb_arch}.tar.gz"; \
    tar -xzf /tmp/singbox.tgz -C /tmp; \
    mv /tmp/sing-box-${SINGBOX_VERSION}-linux-${sb_arch}/sing-box /usr/local/bin/sing-box; \
    chmod +x /usr/local/bin/sing-box; \
    rm -rf /tmp/sing-box-* /tmp/singbox.tgz

WORKDIR /app

COPY pyproject.toml ./
COPY prober ./prober
RUN pip install --upgrade pip && pip install .

EXPOSE 8090
ENV PROBER_HOST=0.0.0.0 \
    PROBER_PORT=8090 \
    SINGBOX_BIN=/usr/local/bin/sing-box

CMD ["python", "-m", "prober.main"]
