#!/usr/bin/env bash
# Builds the macOS app and a .dmg to distribute it:
#   dist/Parameter Extractor.app
#   dist/ParameterExtractor-<version>-macOS-<arch>.dmg
#
# Run from anywhere: it uses the project's environment (../.venv, with
# `pip install -e ".[gui,build]"`) by default; PYTHON=/path/to/python overrides.
#   packaging/build_macos.sh
#
# The app is NOT signed for distribution or notarized: on other Macs, Gatekeeper will block
# it until it is (needs an Apple Developer ID). See packaging/README.md. Locally it's signed
# with a self-signed identity when packaging/make_signing_identity.sh has created one, so the
# keychain's "Always Allow" for the stored keys survives rebuilds.
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
# the project's environment (../.venv, where pyinstaller and the app's packages are installed) unless PYTHON says
# otherwise; then an activated environment; then python3
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x "../.venv/bin/python" ]]; then
  PY="../.venv/bin/python"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
else
  PY="python3"
fi
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
  echo "PyInstaller isn't installed for $PY. Install the build tools into the project's environment:" >&2
  echo "  ../.venv/bin/pip install -e \".[gui,build]\"" >&2
  exit 1
fi
VERSION="$("$PY" -c 'import sys; sys.path.insert(0, "src"); import parameter_extractor as p; print(p.__version__)')"
ARCH="$(uname -m)"

"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/parameter_extractor.spec

APP="dist/${NAME}.app"
# the same signing identity on every build keeps the keychain's "Always Allow" for the stored API keys
# (packaging/make_signing_identity.sh creates one); without it PyInstaller's ad-hoc signature stays
SIGN_ID="${SIGN_IDENTITY:-Parameter Extractor Local Signing}"
if security find-identity -p codesigning 2>/dev/null | grep -q "\"$SIGN_ID\""; then
  codesign --force --deep --sign "$SIGN_ID" "$APP" 2>/dev/null
  echo "Signed with '$SIGN_ID' (keychain access is kept across rebuilds)."
else
  echo "Ad-hoc signed: macOS asks again for keychain access after every rebuild."
  echo "  Run packaging/make_signing_identity.sh once to keep it."
fi
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
