#!/usr/bin/env bash
# Creates (once) a self-signed code-signing identity in your login keychain, used by build_macos.sh to sign the app
# with the SAME identity on every rebuild. macOS remembers keychain access ("Always Allow") per signing identity: an
# ad-hoc signed app is a new app after every build, so the stored API keys asked for your password again each time.
#
# Local use only: the certificate isn't trusted by other Macs (a public release needs an Apple Developer ID). No
# password needed -- codesign accepts an untrusted certificate, and the app's identity becomes
# 'identifier <bundle id> and certificate leaf = <this certificate>', the same across rebuilds.
#   packaging/make_signing_identity.sh            (name: "Parameter Extractor Local Signing")
#   SIGN_IDENTITY="My name" packaging/make_signing_identity.sh
# To remove it: Keychain Access > login > My Certificates > delete it.
set -euo pipefail
NAME="${SIGN_IDENTITY:-Parameter Extractor Local Signing}"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
if security find-identity -p codesigning "$KEYCHAIN" | grep -q "\"$NAME\""; then
  echo "The signing identity '$NAME' already exists."
  exit 0
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/cert.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $NAME
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CNF
# the system's LibreSSL: its PKCS#12 files import into the macOS keychain (OpenSSL 3+ needs -legacy for that)
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$TMP/key.pem" -out "$TMP/cert.pem" \
  -config "$TMP/cert.cnf" 2>/dev/null
PASS="pe-$RANDOM-$RANDOM"
/usr/bin/openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" -out "$TMP/id.p12" -passout "pass:$PASS" \
  -name "$NAME"
# -T /usr/bin/codesign: codesign may use the key without asking
security import "$TMP/id.p12" -k "$KEYCHAIN" -P "$PASS" -T /usr/bin/codesign >/dev/null
echo "Created the signing identity '$NAME' (valid 10 years) in your login keychain."
echo "Rebuild (packaging/build_macos.sh); the first launch of each app asks once more -- choose 'Always Allow'."
