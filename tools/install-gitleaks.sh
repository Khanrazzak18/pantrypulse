#!/bin/sh
# Installs the gitleaks secret scanner into .tools/bin (a folder git ignores). Pinned to one version,
# and the download is checked against the checksums file published with the release.
set -eu
VERSION="8.30.1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/.tools/bin"
if [ -x "$DEST/gitleaks" ] && "$DEST/gitleaks" version 2>/dev/null | grep -q "$VERSION"; then
  echo "gitleaks $VERSION is already installed."
  exit 0
fi
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PLATFORM="darwin_arm64" ;;
  Darwin-x86_64) PLATFORM="darwin_x64" ;;
  Linux-x86_64) PLATFORM="linux_x64" ;;
  Linux-aarch64) PLATFORM="linux_arm64" ;;
  *) echo "No gitleaks build known for $(uname -s) $(uname -m)."; exit 1 ;;
esac
BASE="https://github.com/gitleaks/gitleaks/releases/download/v$VERSION"
FILE="gitleaks_${VERSION}_${PLATFORM}.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$BASE/$FILE" -o "$TMP/$FILE"
curl -fsSL "$BASE/gitleaks_${VERSION}_checksums.txt" -o "$TMP/checksums.txt"
EXPECTED="$(grep " $FILE\$" "$TMP/checksums.txt" | cut -d' ' -f1)"
ACTUAL="$(shasum -a 256 "$TMP/$FILE" | cut -d' ' -f1)"
if [ -z "$EXPECTED" ] || [ "$EXPECTED" != "$ACTUAL" ]; then
  echo "Checksum mismatch for $FILE: refusing to install."
  exit 1
fi
mkdir -p "$DEST"
tar -xzf "$TMP/$FILE" -C "$DEST" gitleaks
chmod +x "$DEST/gitleaks"
echo "Installed gitleaks $VERSION in $DEST."
