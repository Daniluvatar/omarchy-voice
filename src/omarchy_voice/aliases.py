"""User-approved, exact spoken application aliases. Never parse desktop Exec strings."""

import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .core import APP, APP_ALIASES, DesktopRegistry, ROLE_LAUNCH, VoiceError, parse

DESKTOP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.desktop\Z")
MAX_ALIASES = 32


def _directory():
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    if not base.is_absolute():
        raise VoiceError("XDG_CONFIG_HOME must be absolute")
    directory = base / "omarchy-voice"
    try:
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        base_info = base.lstat()
        if not stat.S_ISDIR(base_info.st_mode) or base_info.st_uid != os.getuid() or base_info.st_mode & 0o022:
            raise VoiceError("Unsafe config directory")
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise VoiceError("Unsafe alias directory")
    except OSError as exc:
        raise VoiceError("Cannot access alias directory") from exc
    return directory


def _path():
    return _directory() / "aliases.json"


def read_aliases():
    path = _path()
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 8192:
            raise VoiceError("Unsafe alias file")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise VoiceError("Cannot read aliases") from exc
    if type(data) is not dict or len(data) > MAX_ALIASES or any(
        type(key) is not str or not APP.fullmatch(key) or ".." in key
        or type(value) is not str or not DESKTOP_ID.fullmatch(value)
        for key, value in data.items()
    ):
        raise VoiceError("Invalid aliases")
    return data


def _save(aliases):
    directory = _directory()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix=".aliases-", delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            json.dump(aliases, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / "aliases.json")
    except OSError as exc:
        raise VoiceError("Cannot save aliases") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _phrase_text(phrase):
    if type(phrase) is not str or len(phrase) > 128:
        raise VoiceError("Invalid alias")
    phrase = " ".join(phrase.lower().strip().split())
    if not phrase.startswith(("open ", "launch ", "start ")):
        phrase = "open " + phrase
    return phrase


def _alias_key(phrase):
    intent = parse(_phrase_text(phrase))
    if intent.action != "app.launch":
        raise VoiceError("Alias must name an application")
    key = intent.parameters["application"]
    if not APP.fullmatch(key) or ".." in key:
        raise VoiceError("Invalid alias")
    return key


def _desktop_id_for_path(path, registry):
    return next(
        (str(path.relative_to(root)).replace("/", "-") for root in registry.roots if path.is_relative_to(root)),
        None,
    )


def _application_label(desktop_id, registry):
    for app in registry.applications():
        if app["id"] == desktop_id and app.get("name"):
            return app["name"]
    return "another application"


def _reject_if_taken(phrase, desktop_id, config):
    """Reject a phrase that already opens a different specific application.

    App names stay with that app: saving "open chromium" cannot rewrite Brave.
    "open browser" is a role. With no saved browser phrase it follows the OS
    default, so the first explicit save may pin that one phrase. It does not
    move "open brave" or "open chromium".
    """
    text = _phrase_text(phrase)
    spoken = text.split(" ", 1)[1]
    registry = DesktopRegistry(aliases=config.aliases)
    try:
        intent = parse(text)
    except VoiceError:
        intent = None
    application = intent.parameters["application"] if intent is not None and intent.action == "app.launch" else None
    if application in ROLE_LAUNCH and application not in config.aliases:
        return
    current_id = None
    if application and application not in ROLE_LAUNCH:
        try:
            current_id = _desktop_id_for_path(registry.resolve(application), registry)
        except VoiceError:
            current_id = None
    if current_id and current_id != desktop_id:
        raise VoiceError(
            "That voice command is already taken; it opens " + _application_label(current_id, registry)
        )
    canonical = APP_ALIASES.get(spoken)
    configured = config.aliases.get(canonical) if canonical else None
    if configured and configured != desktop_id:
        raise VoiceError(
            "That voice command is already taken; it opens " + _application_label(configured, registry)
        )


def _desktop_id(application, config):
    if type(application) is not str:
        raise VoiceError("Invalid application")
    registry = DesktopRegistry(aliases=config.aliases)
    path = registry.resolve(application.lower().strip())
    desktop_id = _desktop_id_for_path(path, registry)
    if not desktop_id or not DESKTOP_ID.fullmatch(desktop_id):
        raise VoiceError("Invalid application")
    return desktop_id


def set_alias(phrase, application, config):
    key = _alias_key(phrase)
    desktop_id = _desktop_id(application, config)
    _reject_if_taken(phrase, desktop_id, config)
    aliases = read_aliases()
    if key not in aliases and len(aliases) >= MAX_ALIASES:
        raise VoiceError("Too many aliases")
    aliases[key] = desktop_id
    _save(aliases)
    return key, desktop_id


def update_alias(old_phrase, new_phrase, application, config):
    """Replace one saved mapping atomically without overwriting another phrase."""
    old_key = " ".join(old_phrase.lower().strip().split()) if type(old_phrase) is str else ""
    aliases = read_aliases()
    if old_key not in aliases:
        raise VoiceError("Alias not found")
    new_key = _alias_key(new_phrase)
    if new_key != old_key and new_key in aliases:
        raise VoiceError("Alias already exists")
    desktop_id = _desktop_id(application, config)
    _reject_if_taken(new_phrase, desktop_id, config)
    del aliases[old_key]
    aliases[new_key] = desktop_id
    _save(aliases)
    return new_key, desktop_id


def remove_alias(phrase):
    if type(phrase) is not str:
        raise VoiceError("Invalid alias")
    key = " ".join(phrase.lower().strip().split())
    aliases = read_aliases()
    if key not in aliases:
        raise VoiceError("Alias not found")
    del aliases[key]
    _save(aliases)
    return key


def _settings_path():
    return _directory() / "settings.json"


def read_settings():
    path = _settings_path()
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1024:
            raise VoiceError("Unsafe settings file")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"keybind_osd": True}
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise VoiceError("Cannot read settings") from exc
    if type(data) is not dict or set(data) - {"keybind_osd"} or type(data.get("keybind_osd", True)) is not bool:
        raise VoiceError("Invalid settings")
    return {"keybind_osd": data.get("keybind_osd", True)}


def set_keybind_osd(enabled):
    if type(enabled) is not bool:
        raise VoiceError("Invalid settings")
    settings = read_settings()
    settings["keybind_osd"] = enabled
    directory = _directory()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix=".settings-", delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            json.dump(settings, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / "settings.json")
    except OSError as exc:
        raise VoiceError("Cannot save settings") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return enabled
