"""Where the Slack bot token lives.

The token is kept in the operating-system keyring (Windows Credential
Manager), next to the Setup capture API keys, and is never written to scan
files, logs, slides or the system export.  Without keyring it is kept only
until ZMeter closes.  The Slack email is deliberately not stored anywhere.
"""

from __future__ import annotations

KEYRING_SERVICE = "ZMeter"
KEYRING_USER = "slack_bot_token"


class SlackTokenStore:
    def __init__(self):
        self._session_token = ""
        try:
            import keyring  # noqa: F401

            self.keyring_available = True
        except Exception:  # noqa: BLE001
            self.keyring_available = False

    def get(self) -> str:
        if self._session_token:
            return self._session_token
        if not self.keyring_available:
            return ""
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
        except Exception:  # noqa: BLE001
            return ""

    def set(self, token: str) -> bool:
        """Store (or clear, when empty) the token; True when saved persistently."""

        token = (token or "").strip()
        self._session_token = token
        if not self.keyring_available:
            return False
        try:
            import keyring

            if token:
                keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
            else:
                try:
                    keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
                except Exception:  # noqa: BLE001 - nothing stored yet
                    pass
            return True
        except Exception:  # noqa: BLE001
            return False
