#!/usr/bin/env bash
#
# Build a portable StarPost AppImage for Linux.
#
# Pipeline:
#   1. PyInstaller bundles the app (Python + Qt + every dependency) into
#      dist/starpost/  — see packaging/starpost.spec.
#   2. That bundle is assembled into an AppDir alongside AppRun, the .desktop
#      entry, and the icon.
#   3. appimagetool packs the AppDir into a single StarPost-<version>-<arch>.AppImage.
#
# We use appimagetool directly (not linuxdeploy-plugin-qt) because PyInstaller's
# PySide6 hook already bundles Qt and its plugins; running the Qt plugin on top
# would double-bundle and can conflict.
#
# Requirements on the BUILD machine:
#   - Python 3.11+ with the project's dependencies AND PyInstaller installed
#     (pip install -e ".[dev]"), ideally inside a virtualenv.
#   - curl (to fetch appimagetool) or a pre-downloaded appimagetool on PATH.
#   - For best portability, build on the OLDEST glibc / distro you must support;
#     glibc is forward- but not backward-compatible, so an AppImage built on a
#     new distro may refuse to start on older ones.
#
# Usage:
#   packaging/build_appimage.sh            # build for the host architecture
#   ARCH=aarch64 packaging/build_appimage.sh
#
set -euo pipefail

# Repo root (this script lives in packaging/).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP="starpost"                 # PyInstaller binary name / .desktop basename
NAME="StarPost"                # human-facing app name
ARCH="${ARCH:-$(uname -m)}"    # x86_64, aarch64, ...
# Version is the single source of truth in src/starpost/__init__.py
# (pyproject.toml derives it from there via setuptools' dynamic attr).
VERSION="$(grep -m1 '^__version__' src/starpost/__init__.py | sed -E 's/.*"([^"]+)".*/\1/')"

DIST="dist/${APP}"
APPDIR="build/${NAME}.AppDir"
TOOLS="build/tools"
ICON_SRC="src/starpost/gui/resources/StarPost-logo.png"
OUT="${NAME}-${VERSION}-${ARCH}.AppImage"

echo ">> StarPost ${VERSION} → ${OUT} (arch ${ARCH})"

# --- 1. PyInstaller bundle -------------------------------------------------
if ! python3 -c "import PyInstaller" 2>/dev/null; then
  echo "ERROR: PyInstaller is not installed in this Python environment." >&2
  echo "       Run:  pip install -e \".[dev]\"   (ideally in a virtualenv)" >&2
  exit 1
fi
echo ">> [1/3] Running PyInstaller…"
python3 -m PyInstaller --noconfirm packaging/starpost.spec

if [ ! -x "${DIST}/${APP}" ]; then
  echo "ERROR: expected bundle ${DIST}/${APP} was not produced." >&2
  exit 1
fi

# --- 2. Assemble the AppDir ------------------------------------------------
echo ">> [2/3] Assembling ${APPDIR}…"
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
cp -a "${DIST}/." "${APPDIR}/usr/bin/"

install -Dm755 packaging/AppRun            "${APPDIR}/AppRun"
# appimagetool wants the .desktop and icon at the AppDir root (named to match
# the desktop's Icon= key), and it's good practice to also place them in the
# usual share/ locations for when the app is integrated into a menu.
install -Dm644 packaging/starpost.desktop  "${APPDIR}/${APP}.desktop"
install -Dm644 packaging/starpost.desktop  "${APPDIR}/usr/share/applications/${APP}.desktop"
install -Dm644 "${ICON_SRC}"               "${APPDIR}/${APP}.png"
install -Dm644 "${ICON_SRC}"               "${APPDIR}/usr/share/icons/hicolor/256x256/apps/${APP}.png"

# --- 3. Pack with appimagetool ---------------------------------------------
echo ">> [3/3] Packing with appimagetool…"
TOOL="$(command -v appimagetool || true)"
if [ -z "${TOOL}" ]; then
  mkdir -p "${TOOLS}"
  TOOL="${TOOLS}/appimagetool-${ARCH}.AppImage"
  if [ ! -x "${TOOL}" ]; then
    echo ">> fetching appimagetool…"
    curl -fL -o "${TOOL}" \
      "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    chmod +x "${TOOL}"
  fi
fi

# --appimage-extract-and-run lets appimagetool run without a working FUSE mount
# (common in containers/CI). ARCH must be exported for appimagetool to label it.
ARCH="${ARCH}" "${TOOL}" --appimage-extract-and-run "${APPDIR}" "${OUT}"

echo ">> Done: ${OUT}"
echo "   Test it with:  ./${OUT}"
