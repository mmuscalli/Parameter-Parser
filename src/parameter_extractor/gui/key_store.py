"""
Optional storage of the user's API key in the operating system's credential
store (macOS Keychain, Windows Credential Manager, Secret Service on Linux)
via `keyring`. Never written to a plain file.

Every function fails soft: if no credential store is available, the app
simply doesn't remember the key and the user pastes it each time.
"""
from __future__ import annotations

SERVICE = "parameter-extractor"
ACCOUNT = "anthropic-api-key"
ADS_ACCOUNT = "ads-api-token"          # optional NASA ADS token (ADS bibcode lookups)


def load_key(account: str = ACCOUNT) -> str:
    try:
        import keyring
        return keyring.get_password(SERVICE, account) or ""
    except Exception:
        return ""


def save_key(key: str, account: str = ACCOUNT) -> bool:
    try:
        import keyring
        keyring.set_password(SERVICE, account, key)
        return True
    except Exception:
        return False


def delete_key(account: str = ACCOUNT) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, account)
    except Exception:
        pass  # nothing stored, or no credential store -- either way, nothing to delete
