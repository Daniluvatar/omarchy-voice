"""Strict TOML configuration. Missing files use safe local defaults."""

from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import re
import stat
import tempfile
import tomllib
from .core import ACTIONS, APP, VoiceError
from .aliases import read_aliases

STT_PROVIDERS = ("faster-whisper",)
STT_MODELS = ("tiny.en", "base.en", "small.en")
STT_DEVICES = ("cpu", "cuda")
STT_LANGUAGES = ("en",)
STT_KEYS = ("provider", "model", "device", "language")
_SCHEMA = {
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


def config_path():
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    if not base.is_absolute():
        raise VoiceError("XDG_CONFIG_HOME must be absolute")
    return base / "omarchy-voice" / "config.toml"


def stt_snapshot(config):
    return {
        "provider": config.provider,
        "model": config.model,
        "device": config.device,
        "language": config.language or "en",
        "compute_type": config.compute_type,
    }


def stt_options(config):
    models = [{"value": name, "label": label} for name, label in (
        ("tiny.en", "tiny.en (fastest)"),
        ("base.en", "base.en"),
        ("small.en", "small.en (more accurate)"),
    )]
    if config.model not in STT_MODELS:
        models.append({"value": config.model, "label": config.model})
    devices = [{"value": "cpu", "label": "CPU"}]
    if config.device == "cuda" or Path("/dev/nvidia0").exists():
        devices.append({"value": "cuda", "label": "CUDA"})
    languages = [{"value": "en", "label": "English"}]
    return {
        "providers": [{"value": "faster-whisper", "label": "faster-whisper (local)"}],
        "capabilities": {
            "faster-whisper": {
                "model": models,
                "device": devices,
                "language": languages,
            }
        },
    }


def _toml_escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _toml_value(value):
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float) and type(value) is not bool:
        return str(value)
    if type(value) is list:
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return '"' + _toml_escape(value) + '"'


def _emit_toml(data):
    chunks = []
    for section in ("stt", "audio", "confirmation", "notifications", "permissions", "applications"):
        if section not in data:
            continue
        table = data[section]
        if type(table) is not dict:
            raise VoiceError("Invalid configuration")
        if section == "applications":
            aliases = table.get("aliases") or {}
            if type(aliases) is not dict:
                raise VoiceError("Invalid configuration")
            chunks.append("[applications.aliases]")
            for key, value in aliases.items():
                chunks.append(f'{key} = {_toml_value(value)}')
            chunks.append("")
            continue
        chunks.append(f"[{section}]")
        for key, value in table.items():
            chunks.append(f"{key} = {_toml_value(value)}")
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def _ensure_config_directory(path):
    directory = path.parent
    try:
        directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise VoiceError("Unsafe config directory")
    except OSError as exc:
        raise VoiceError("Cannot access configuration") from exc


def _read_toml_data(path):
    try:
        if path.stat().st_size > 65536:
            raise VoiceError("Configuration too large")
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, RecursionError) as exc:
        raise VoiceError("Cannot load configuration") from exc


def set_stt(key, value, path=None):
    if key not in STT_KEYS or type(value) is not str:
        raise VoiceError("Invalid STT setting")
    if key == "provider" and value not in STT_PROVIDERS:
        raise VoiceError("Unsupported STT provider")
    if key == "model" and value not in STT_MODELS:
        raise VoiceError("Unsupported STT model")
    if key == "device" and value not in STT_DEVICES:
        raise VoiceError("Invalid STT settings")
    if key == "language" and value not in STT_LANGUAGES:
        raise VoiceError("Invalid language")
    path = config_path() if path is None else Path(path)
    _ensure_config_directory(path)
    try:
        if path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise VoiceError("Unsafe configuration file")
    except OSError as exc:
        raise VoiceError("Cannot access configuration") from exc
    data = _read_toml_data(path)
    if set(data) - set(_SCHEMA):
        raise VoiceError("Unknown configuration section")
    stt = dict(data.get("stt") or {})
    if type(stt) is not dict or set(stt) - _SCHEMA["stt"]:
        raise VoiceError("Unknown configuration setting")
    stt[key] = value
    if key == "device":
        stt["compute_type"] = "int8" if value == "cpu" else "float16"
    data["stt"] = stt
    Config(**_flatten(data))
    text = _emit_toml(data)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".config-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise VoiceError("Cannot save configuration") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return stt_snapshot(load_config(path))


def _flatten(data):
    values = {}
    for section, table in data.items():
        if type(table) is not dict or set(table) - _SCHEMA[section]:
            raise VoiceError("Unknown configuration setting")
        for key, value in table.items():
            target = {
                "confirmation": {"timeout_seconds": "confirmation_seconds"},
                "notifications": {"enabled": "notifications"},
                "permissions": {"allow": "permissions"},
            }.get(section, {}).get(key, key)
            values[target] = value
    return values


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
            defaults = Config()
            return replace(defaults, aliases={**defaults.aliases, **read_aliases()})
        raise VoiceError("Configuration not found")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, RecursionError) as exc:
        raise VoiceError("Cannot load configuration") from exc
    if set(data) - set(_SCHEMA):
        raise VoiceError("Unknown configuration section")
    try:
        config = Config(**_flatten(data))
        return replace(config, aliases={**config.aliases, **read_aliases()})
    except (TypeError, ValueError) as exc:
        raise VoiceError("Invalid configuration") from exc
