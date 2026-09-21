"""Strict TOML configuration. Missing files use safe local defaults."""

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import tomllib
from .core import ACTIONS, APP, VoiceError


@dataclass(frozen=True)
class Config:
    provider: str = "faster-whisper"
    model: str = "tiny.en"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str | None = "en"
    max_seconds: float = 15
    timeout_seconds: float = 60
    confirmation_seconds: float = 15
    notifications: bool = False
    permissions: tuple = tuple(sorted(ACTIONS))
    aliases: dict = field(
        default_factory=lambda: {
            "brave": "brave-browser.desktop",
            "spotify": "spotify.desktop",
        }
    )

    def __post_init__(self):
        if self.provider != "faster-whisper":
            raise VoiceError("Unsupported STT provider")
        if type(self.model) is not str or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}", self.model
        ):
            raise VoiceError("Invalid model")
        if self.device not in ("cpu", "cuda") or self.compute_type not in (
            "int8",
            "float16",
            "float32",
            "int8_float16",
        ):
            raise VoiceError("Invalid STT settings")
        if self.language is not None and (
            type(self.language) is not str
            or not re.fullmatch("[a-z]{2,3}", self.language)
        ):
            raise VoiceError("Invalid language")
        for value, maximum in [
            (self.max_seconds, 120),
            (self.timeout_seconds, 600),
            (self.confirmation_seconds, 120),
        ]:
            if type(value) not in (int, float) or not 0 < value <= maximum:
                raise VoiceError("Invalid timeout")
        if type(self.notifications) is not bool:
            raise VoiceError("Invalid notification setting")
        if not isinstance(self.permissions, (list, tuple)) or any(
            type(a) is not str or a not in ACTIONS for a in self.permissions
        ):
            raise VoiceError("Invalid permissions")
        if type(self.aliases) is not dict:
            raise VoiceError("Invalid aliases")
        for key, value in self.aliases.items():
            if (
                type(key) is not str
                or not APP.fullmatch(key)
                or type(value) is not str
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.desktop", value)
            ):
                raise VoiceError("Invalid application alias")


def load_config(path=None):
    explicit = path is not None
    path = (
        Path(path)
        if explicit
        else Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "omarchy-voice/config.toml"
    )
    try:
        if path.stat().st_size > 65536:
            raise VoiceError("Configuration too large")
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        if not explicit:
            return Config()
        raise VoiceError("Configuration not found")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, RecursionError) as exc:
        raise VoiceError("Cannot load configuration") from exc
    schema = {
        "stt": {
            "provider",
            "model",
            "device",
            "compute_type",
            "language",
            "timeout_seconds",
        },
        "audio": {"max_seconds"},
        "confirmation": {"timeout_seconds"},
        "notifications": {"enabled"},
        "permissions": {"allow"},
        "applications": {"aliases"},
    }
    if set(data) - set(schema):
        raise VoiceError("Unknown configuration section")
    values = {}
    for section, table in data.items():
        if type(table) is not dict or set(table) - schema[section]:
            raise VoiceError("Unknown configuration setting")
        for key, value in table.items():
            target = {
                "confirmation": {"timeout_seconds": "confirmation_seconds"},
                "notifications": {"enabled": "notifications"},
                "permissions": {"allow": "permissions"},
            }.get(section, {}).get(key, key)
            values[target] = value
    try:
        return Config(**values)
    except (TypeError, ValueError) as exc:
        raise VoiceError("Invalid configuration") from exc
