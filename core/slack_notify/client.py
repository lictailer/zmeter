"""Minimal Slack Web API client for a bot token (``xoxb-...``).

Plain blocking HTTP calls with short timeouts.  Only the notifier's worker
thread calls these; nothing here touches Qt.  Bot token scopes needed:
``chat:write``, ``files:write``, ``im:write``, ``users:read``,
``users:read.email``.
"""

from __future__ import annotations

import json

API_URL = "https://slack.com/api/"
# (connect, read) seconds for every HTTP request.
TIMEOUT = (5, 10)


class SlackError(RuntimeError):
    """A Slack call failed; ``code`` is Slack's error word when it sent one."""

    def __init__(self, method: str, code: str):
        super().__init__(f"{method}: {code}")
        self.method = method
        self.code = code


def _default_session():
    import requests

    return requests.Session()


class SlackClient:
    def __init__(self, token: str, session=None):
        self.token = (token or "").strip()
        self.session = session if session is not None else _default_session()

    # ------------------------------------------------------------ helpers --
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _call(self, method: str, *, params=None, data=None, http="post") -> dict:
        url = API_URL + method
        try:
            if http == "get":
                response = self.session.get(
                    url, params=params, headers=self._headers(), timeout=TIMEOUT
                )
            else:
                response = self.session.post(
                    url, data=data, headers=self._headers(), timeout=TIMEOUT
                )
        except Exception as exc:  # noqa: BLE001 - network errors of any kind
            raise SlackError(method, f"{type(exc).__name__}: {exc}") from exc
        status = getattr(response, "status_code", 200)
        if status == 429:
            raise SlackError(method, "rate_limited")
        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise SlackError(method, f"HTTP {status}, not JSON") from exc
        if not isinstance(body, dict) or not body.get("ok"):
            code = body.get("error", "unknown_error") if isinstance(body, dict) else "unknown_error"
            raise SlackError(method, str(code))
        return body

    # ---------------------------------------------------------------- API --
    def auth_test(self) -> dict:
        return self._call("auth.test")

    def lookup_user_id(self, email: str) -> str:
        body = self._call(
            "users.lookupByEmail", params={"email": email.strip()}, http="get"
        )
        try:
            return str(body["user"]["id"])
        except (KeyError, TypeError):
            raise SlackError("users.lookupByEmail", "no_user_id") from None

    def open_dm(self, user_id: str) -> str:
        body = self._call("conversations.open", data={"users": user_id})
        try:
            return str(body["channel"]["id"])
        except (KeyError, TypeError):
            raise SlackError("conversations.open", "no_channel_id") from None

    def post_text(self, channel: str, text: str) -> None:
        self._call("chat.postMessage", data={"channel": channel, "text": text})

    def upload_png(self, channel: str, png: bytes, filename: str, comment: str) -> None:
        """Post ``comment`` with one PNG attached, as a single message."""

        if not png:
            raise SlackError("files.getUploadURLExternal", "empty_file")
        ticket = self._call(
            "files.getUploadURLExternal",
            data={"filename": filename, "length": str(len(png))},
        )
        upload_url = ticket.get("upload_url")
        file_id = ticket.get("file_id")
        if not upload_url or not file_id:
            raise SlackError("files.getUploadURLExternal", "no_upload_url")
        try:
            response = self.session.post(
                upload_url,
                data=png,
                headers={"Content-Type": "application/octet-stream"},
                timeout=TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            raise SlackError("file upload", f"{type(exc).__name__}: {exc}") from exc
        status = getattr(response, "status_code", 200)
        if not 200 <= int(status) < 300:
            raise SlackError("file upload", f"HTTP {status}")
        self._call(
            "files.completeUploadExternal",
            data={
                "files": json.dumps([{"id": file_id, "title": filename}]),
                "channel_id": channel,
                "initial_comment": comment,
            },
        )
