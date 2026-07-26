#!/bin/bash
# Builds a CHIRP AppImage from this git checkout.
#
# Must run on an x86_64 Ubuntu 22.04 (jammy) host, or a container/VM of one:
# that's the platform the bundled wxPython/GTK3 apt packages come from.
#
# Usage: ./appimage/build.sh
# Output: appimage/out/CHIRP-<version>-x86_64.AppImage
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO_ROOT="$(pwd)"
RECIPE_TEMPLATE="$REPO_ROOT/appimage/AppImageBuilder.yml"
OUT_DIR="$REPO_ROOT/appimage/out"

if ! grep -q 'jammy' /etc/os-release 2>/dev/null; then
    echo "warning: this doesn't look like Ubuntu 22.04 (jammy)." >&2
    echo "         the recipe pins jammy apt sources for wxPython/GTK3; other hosts may not work." >&2
fi

VERSION="$(git describe --tags --always --dirty 2>/dev/null || echo dev)"
echo "Building CHIRP AppImage version: $VERSION"

SUDO=""
[ "$(id -u)" != "0" ] && SUDO="sudo"

echo "Installing build dependencies..."
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq \
    python3.10 python3-pip python3-venv \
    fuse libfuse2 desktop-file-utils \
    binutils coreutils fakeroot squashfs-tools patchelf zsync \
    libgdk-pixbuf2.0-bin libglib2.0-bin gtk-update-icon-cache gettext

export APPIMAGE_EXTRACT_AND_RUN=1

if ! command -v appimage-builder >/dev/null 2>&1; then
    echo "Installing appimage-builder..."
    # appimage-builder compares raw Debian version strings (e.g. "1.21.1ubuntu2")
    # with packaging.version.parse(), which only works with packaging's old
    # LegacyVersion fallback -- removed in packaging>=22. Pin below that.
    python3.10 -m pip install --user --quiet appimage-builder "packaging<22"
    export PATH="$HOME/.local/bin:$PATH"
fi

mkdir -p "$OUT_DIR"
rm -rf "$REPO_ROOT/AppDir"

RECIPE="$(mktemp --suffix=.yml)"
trap 'rm -f "$RECIPE"' EXIT
sed "s/__CHIRP_VERSION__/$VERSION/g" "$RECIPE_TEMPLATE" > "$RECIPE"

appimage-builder --recipe "$RECIPE" --skip-test

mv "$REPO_ROOT"/CHIRP-"$VERSION"-x86_64.AppImage* "$OUT_DIR/"
rm -rf "$REPO_ROOT/AppDir"

echo "Built: $OUT_DIR/CHIRP-$VERSION-x86_64.AppImage"
