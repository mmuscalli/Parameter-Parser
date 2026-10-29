#!/usr/bin/env bash
# Builds the macOS app and a .dmg to distribute it:
#   dist/Parameter Extractor.app
#   dist/ParameterExtractor-<version>-macOS-<arch>.dmg
#
# Run from anywhere, with the project's Python environment that has
# `pip install -e ".[gui]"` and pyinstaller installed:
#   PYTHON=../.venv/bin/python packaging/build_macos.sh
#
# The app is NOT code-signed or notarized: on other Macs, Gatekeeper will block
# it until it is (needs an Apple Developer ID). See packaging/README.md.
# Developer build (adds the developer-only handoff mode; never distribute it):
#   PYTHON=../.venv/bin/python packaging/build_macos.sh --dev   -> dist/Parameter Extractor Dev.app
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="Parameter Extractor"
if [[ "${1:-}" == "--dev" ]]; then
  export PE_DEV_BUILD=1
  NAME="Parameter Extractor Dev"
else
  unset PE_DEV_BUILD
fi
PY="${PYTHON:-python3}"
VERSION="$("$PY" -c 'import sys; sys.path.insert(0, "src"); import parameter_extractor as p; print(p.__version__)')"
ARCH="$(uname -m)"

"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/parameter_extractor.spec

APP="dist/${NAME}.app"
echo "Built: $APP ($(du -sh "$APP" | cut -f1))"
if [[ -n "${PE_DEV_BUILD:-}" ]]; then
  echo "Developer build: no .dmg (not for distribution)."
  echo "Self-check: \"$APP/Contents/MacOS/$NAME\" --self-check"
  exit 0
fi
DMG="dist/ParameterExtractor-${VERSION}-macOS-${ARCH}.dmg"
rm -f "$DMG"
hdiutil create -quiet -volname "Parameter Extractor" -srcfolder "$APP" -ov -format UDZO "$DMG"

echo "       $DMG ($(du -sh "$DMG" | cut -f1))"
echo "Self-check: \"$APP/Contents/MacOS/Parameter Extractor\" --self-check"
