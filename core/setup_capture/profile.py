"""Per-PC setup-capture settings: lab-context folder, experiment description,
the AI provider (Claude or DeepSeek), its model and its API key.

The lab-context files live in ``<repository>/lab_context`` beside the device
workbook so each lab edits its own copy.  The experiment description and the
model setting are per Windows user (application-data folder).  The API key is
kept in the operating-system keyring and is never written to scan files,
logs or slides.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

LAB_CONTEXT_DIRNAME = "lab_context"
LAB_CONTEXT_FILE = "lab_context.md"
SUGGESTED_QUESTIONS_FILE = "suggested_questions.md"
KEYRING_SERVICE = "ZMeter"

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
DEFAULT_PROVIDER = PROVIDER_ANTHROPIC
PROVIDERS = {
    PROVIDER_ANTHROPIC: {
        "label": "Claude (Anthropic)",
        "default_model": "claude-sonnet-5-5",
        "keyring_user": "anthropic_api_key",
        "key_hint": "sk-ant-...",
        "base_url": "https://api.anthropic.com/v1/",
    },
    PROVIDER_DEEPSEEK: {
        "label": "DeepSeek",
        "default_model": "deepseek-v4-pro",
        "keyring_user": "deepseek_api_key",
        "key_hint": "sk-...",
        "base_url": "https://api.deepseek.com",
    },
    PROVIDER_OPENAI_COMPATIBLE: {
        "label": "Other (OpenAI-compatible)",
        "default_model": "",
        "keyring_user": "openai_compatible_api_key",
        "key_hint": "provider's API key",
        "base_url": "",
    },
}
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER]["default_model"]
# Claude effort: low keeps thinking (most of the cost) short.
EFFORT_LEVELS = ("low", "medium", "high")
DEFAULT_EFFORT = "low"
# DeepSeek V4 thinks by default; this job does not need it and it takes most
# of the time, so it is off unless the user turns it on.
DEFAULT_THINKING = False


def provider_info(provider: str | None) -> dict:
    return PROVIDERS.get(provider or "", PROVIDERS[DEFAULT_PROVIDER])


def default_model(provider: str | None) -> str:
    return provider_info(provider)["default_model"]

DESCRIPTION_FIELDS = (
    ("device", "Device / sample"),
    ("pins_in_use", "Pins in use"),
    ("gates", "Gates"),
    ("contacts", "Contact geometry"),
    ("notes", "Notes"),
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def lab_context_dir() -> Path:
    return repository_root() / LAB_CONTEXT_DIRNAME


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def lab_context_text(folder: Path | None = None) -> str:
    return read_text_file((folder or lab_context_dir()) / LAB_CONTEXT_FILE)


def suggested_questions_text(folder: Path | None = None) -> str:
    return read_text_file((folder or lab_context_dir()) / SUGGESTED_QUESTIONS_FILE)


def lab_context_version(text: str) -> str:
    """First heading line of lab_context.md, saved with each questionnaire."""

    for line in text.splitlines():
        line = line.strip()
        if line:
            return line.lstrip("#").strip()[:200]
    return ""


def _settings_dir() -> Path:
    base = None
    try:
        from PyQt6 import QtCore

        base = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.GenericDataLocation
        )
    except Exception:  # noqa: BLE001 - Qt may be missing in pure tests
        base = None
    if not base:
        base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "ZMeter" / "setup_capture"


class SetupCaptureSettings:
    """Small JSON-backed store for the description, provider and models."""

    FILENAME = "settings.json"

    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder) if folder is not None else _settings_dir()
        self.data = {"description": {}, "provider": DEFAULT_PROVIDER, "models": {}}
        self.load()

    @property
    def path(self) -> Path:
        return self.folder / self.FILENAME

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            if isinstance(raw.get("description"), dict):
                self.data["description"] = {
                    key: str(raw["description"].get(key, ""))
                    for key, _label in DESCRIPTION_FIELDS
                }
            if raw.get("provider") in PROVIDERS:
                self.data["provider"] = raw["provider"]
            if isinstance(raw.get("models"), dict):
                self.data["models"] = {
                    key: str(value).strip()
                    for key, value in raw["models"].items()
                    if key in PROVIDERS and str(value).strip()
                }
            if isinstance(raw.get("model"), str) and raw["model"].strip():
                # Settings written before DeepSeek support held one Claude model.
                self.data["models"].setdefault(PROVIDER_ANTHROPIC, raw["model"].strip())
            if isinstance(raw.get("base_urls"), dict):
                self.data["base_urls"] = {
                    key: str(value).strip()
                    for key, value in raw["base_urls"].items()
                    if key in PROVIDERS and str(value).strip()
                }
            if raw.get("effort") in EFFORT_LEVELS:
                self.data["effort"] = raw["effort"]
            if isinstance(raw.get("thinking"), bool):
                self.data["thinking"] = raw["thinking"]
            if isinstance(raw.get("last_answers"), list):
                self.data["last_answers"] = raw["last_answers"]

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    @property
    def description(self) -> dict:
        return {
            key: str(self.data["description"].get(key, ""))
            for key, _label in DESCRIPTION_FIELDS
        }

    def set_description(self, description: dict) -> None:
        self.data["description"] = {
            key: str(description.get(key, "")).strip()
            for key, _label in DESCRIPTION_FIELDS
        }
        self.save()

    @property
    def provider(self) -> str:
        provider = self.data.get("provider")
        return provider if provider in PROVIDERS else DEFAULT_PROVIDER

    def model_for(self, provider: str | None = None) -> str:
        provider = provider or self.provider
        return self.data.get("models", {}).get(provider) or default_model(provider)

    @property
    def model(self) -> str:
        return self.model_for(self.provider)

    def base_url_for(self, provider: str | None = None) -> str:
        provider = provider or self.provider
        return self.data.get("base_urls", {}).get(provider) or provider_info(provider).get("base_url", "")

    def set_base_url(self, provider: str, url: str) -> None:
        url = (url or "").strip()
        urls = self.data.setdefault("base_urls", {})
        if url and url != provider_info(provider).get("base_url", ""):
            urls[provider] = url
        else:
            urls.pop(provider, None)

    @property
    def effort(self) -> str:
        effort = self.data.get("effort")
        return effort if effort in EFFORT_LEVELS else DEFAULT_EFFORT

    @property
    def thinking(self) -> bool:
        value = self.data.get("thinking")
        return value if isinstance(value, bool) else DEFAULT_THINKING

    def set_effort(self, effort: str) -> None:
        self.data["effort"] = effort if effort in EFFORT_LEVELS else DEFAULT_EFFORT
        self.save()

    def set_provider_model(self, provider: str, model: str) -> None:
        if provider not in PROVIDERS:
            provider = DEFAULT_PROVIDER
        self.data["provider"] = provider
        self.data.setdefault("models", {})[provider] = (model or "").strip() or default_model(provider)
        self.data.pop("model", None)
        self.save()


class ApiKeyStore:
    """API keys (one per provider) in the OS keyring; falls back to memory
    for this session only."""

    def __init__(self):
        self._session_keys: dict[str, str] = {}
        try:
            import keyring  # noqa: F401

            self.keyring_available = True
        except Exception:  # noqa: BLE001
            self.keyring_available = False

    def get(self, provider: str = DEFAULT_PROVIDER) -> str:
        if self._session_keys.get(provider):
            return self._session_keys[provider]
        if not self.keyring_available:
            return ""
        try:
            import keyring

            user = provider_info(provider)["keyring_user"]
            return keyring.get_password(KEYRING_SERVICE, user) or ""
        except Exception:  # noqa: BLE001
            return ""

    def set(self, key: str, provider: str = DEFAULT_PROVIDER) -> bool:
        """Store the key; return True when it was saved persistently."""

        key = (key or "").strip()
        self._session_keys[provider] = key
        user = provider_info(provider)["keyring_user"]
        if not self.keyring_available:
            return False
        try:
            import keyring

            if key:
                keyring.set_password(KEYRING_SERVICE, user, key)
            else:
                try:
                    keyring.delete_password(KEYRING_SERVICE, user)
                except Exception:  # noqa: BLE001 - nothing stored yet
                    pass
            return True
        except Exception:  # noqa: BLE001
            return False
