#!/usr/bin/env bash
# Download a sing-box release tarball into /usr/local/bin for non-Docker installs.
set -euo pipefail

VERSION="${SINGBOX_VERSION:-1.10.7}"

uname_m="$(uname -m)"
case "$uname_m" in
  x86_64|amd64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  armv7l|armv7) arch=armv7 ;;
  *) echo "unsupported arch: $uname_m" >&2; exit 1 ;;
esac

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$os" in
  linux|darwin) ;;
  *) echo "unsupported os: $os" >&2; exit 1 ;;
esac

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

url="https://github.com/SagerNet/sing-box/releases/download/v${VERSION}/sing-box-${VERSION}-${os}-${arch}.tar.gz"
echo "downloading $url"
curl -fsSL "$url" -o "$tmpdir/sb.tgz"
tar -xzf "$tmpdir/sb.tgz" -C "$tmpdir"

dest="${SINGBOX_DEST:-/usr/local/bin/sing-box}"
sudo install -m 0755 "$tmpdir/sing-box-${VERSION}-${os}-${arch}/sing-box" "$dest"
echo "installed $dest"
"$dest" version
