"""User-approved, exact spoken voice commands. Never parse desktop Exec strings.

A voice command maps a reviewed spoken phrase to an installed application.
New saves go to ``voice_commands.json``; pre-rename saves in ``aliases.json``
are migrated once into that file and then left untouched as a backup.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .core import APP, BUILTIN_APP_NAMES, DesktopRegistry, ROLE_LAUNCH, VoiceError, parse

DESKTOP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.desktop\Z")
MAX_VOICE_COMMANDS = 32
STORE_FILE = "voice_commands.json"
LEGACY_STORE_FILE = "aliases.json"


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
            raise VoiceError("Unsafe voice command directory")
    except OSError as exc:
        raise VoiceError("Cannot access voice command directory") from exc
    return directory


def _store_path():
    return _directory() / STORE_FILE


def _legacy_store_path():
    return _directory() / LEGACY_STORE_FILE


def _load_store_file(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise VoiceError("Cannot read voice commands") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 8192:
        raise VoiceError("Unsafe voice command file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise VoiceError("Cannot read voice commands") from exc
    if type(data) is not dict or len(data) > MAX_VOICE_COMMANDS or any(
        type(key) is not str or not APP.fullmatch(key) or ".." in key
        or type(value) is not str or not DESKTOP_ID.fullmatch(value)
        for key, value in data.items()
    ):
        raise VoiceError("Invalid voice commands")
    return data


def _migrate_legacy(directory):
    """Copy a valid pre-rename store into the canonical store.

    The legacy file is never modified or deleted. Returns the validated
    legacy data, or ``None`` when the canonical store already exists or there
    is nothing to migrate, so removed phrases never reappear from legacy data.
    """
    legacy = directory / LEGACY_STORE_FILE
    if (directory / STORE_FILE).exists() or not legacy.exists():
        return None
    return _load_store_file(legacy)


def read_voice_commands():
    """Return validated voice commands, migrating a legacy store once.

    If a ``voice_commands.json`` exists (even an unsafe one) it is validated
    and rejected loudly rather than clobbered. Otherwise a valid
    ``aliases.json`` is copied into it atomically; if that write fails, the
    already-validated legacy data is still returned unmodified for this read.
    """
    directory = _directory()
    canonical = directory / STORE_FILE
    try:
        canonical.lstat()
    except FileNotFoundError:
        pass  # No canonical store at all; the legacy store may provide it.
    else:
        return _load_store_file(canonical)
    legacy = _migrate_legacy(directory)
    if legacy is None:
        return {}
    try:
        _save(legacy)
    except VoiceError:
        pass  # Write failed: keep serving the validated legacy data untouched.
    return legacy


def _save(voice_commands):
    directory = _directory()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix=".voice-commands-", delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            json.dump(voice_commands, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, _store_path())
    except OSError as exc:
        raise VoiceError("Cannot save voice commands") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def voice_commands_revision(voice_commands):
    """Deterministic 16-hex digest of the stored mapping; never the contents."""
    payload = json.dumps(voice_commands, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _phrase_text(phrase):
    if type(phrase) is not str or len(phrase) > 128:
        raise VoiceError("Invalid voice command")
    phrase = " ".join(phrase.lower().strip().split())
    if not phrase.startswith(("open ", "launch ", "start ")):
        phrase = "open " + phrase
    return phrase


def _voice_command_key(phrase):
    intent = parse(_phrase_text(phrase))
    if intent.action != "app.launch":
        raise VoiceError("Voice command must name an application")
    key = intent.parameters["application"]
    if not APP.fullmatch(key) or ".." in key:
        raise VoiceError("Invalid voice command")
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
    registry = DesktopRegistry(voice_commands=config.voice_commands)
    try:
        intent = parse(text)
    except VoiceError:
        intent = None
    application = intent.parameters["application"] if intent is not None and intent.action == "app.launch" else None
    if application in ROLE_LAUNCH and application not in config.voice_commands:
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
    canonical = BUILTIN_APP_NAMES.get(spoken)
    configured = config.voice_commands.get(canonical) if canonical else None
    if configured and configured != desktop_id:
        raise VoiceError(
            "That voice command is already taken; it opens " + _application_label(configured, registry)
        )


def _desktop_id(application, config):
    if type(application) is not str:
        raise VoiceError("Invalid application")
    registry = DesktopRegistry(voice_commands=config.voice_commands)
    path = registry.resolve(application.lower().strip())
    desktop_id = _desktop_id_for_path(path, registry)
    if not desktop_id or not DESKTOP_ID.fullmatch(desktop_id):
        raise VoiceError("Invalid application")
    return desktop_id


def set_voice_command(phrase, application, config):
    key = _voice_command_key(phrase)
    desktop_id = _desktop_id(application, config)
    _reject_if_taken(phrase, desktop_id, config)
    voice_commands = read_voice_commands()
    if key not in voice_commands and len(voice_commands) >= MAX_VOICE_COMMANDS:
        raise VoiceError("Too many voice commands")
    voice_commands[key] = desktop_id
    _save(voice_commands)
    return key, desktop_id


def update_voice_command(old_phrase, new_phrase, application, config):
    """Replace one saved mapping atomically without overwriting another phrase."""
    old_key = " ".join(old_phrase.lower().strip().split()) if type(old_phrase) is str else ""
    voice_commands = read_voice_commands()
    if old_key not in voice_commands:
        raise VoiceError("Voice command not found")
    new_key = _voice_command_key(new_phrase)
    if new_key != old_key and new_key in voice_commands:
        raise VoiceError("Voice command already exists")
    desktop_id = _desktop_id(application, config)
    _reject_if_taken(new_phrase, desktop_id, config)
    del voice_commands[old_key]
    voice_commands[new_key] = desktop_id
    _save(voice_commands)
    return new_key, desktop_id


def remove_voice_command(phrase):
    if type(phrase) is not str:
        raise VoiceError("Invalid voice command")
    key = " ".join(phrase.lower().strip().split())
    voice_commands = read_voice_commands()
    if key not in voice_commands:
        raise VoiceError("Voice command not found")
    del voice_commands[key]
    _save(voice_commands)
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
