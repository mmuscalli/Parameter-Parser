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


def load_key() -> str:
    try:
        import keyring
        return keyring.get_password(SERVICE, ACCOUNT) or ""
    except Exception:
        return ""


def save_key(key: str) -> bool:
    try:
        import keyring
        keyring.set_password(SERVICE, ACCOUNT, key)
        return True
    except Exception:
        return False


def delete_key() -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, ACCOUNT)
    except Exception:
        pass  # nothing stored, or no credential store -- either way, nothing to delete
