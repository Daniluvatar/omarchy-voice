"""Post-action Omarchy OSD. Chord values come from live Hyprland bindings."""

from pathlib import Path
import json
import os
import re
import subprocess
import time

from .core import Intent

OSD_ICON = "󱓞"
OSD_DURATION_MS = 1800
KEYBIND_TTL_SECONDS = 30
MAX_KEYBIND_BYTES = 65536
MAX_CHORD = 48
KEYBIND_LINE = re.compile(r"\A(.{1,48}?)\s+→\s+(.+)\Z")
SAFE_CHORD = re.compile(r"\A[A-Za-z0-9 +_/.-]{1,48}\Z")

# Stable Omarchy Super+K descriptions → voice intents. Chord text is filled
# from `omarchy menu keybindings --print` so user unbinds/overrides apply.
KEYBIND_HINTS = (
    (("app.launch", "terminal"), "Terminal"),
    (("app.launch", "browser"), "Browser"),
    (("app.launch", "brave"), "Browser"),
    (("app.launch", "spotify"), "Music"),
    (("app.launch", "nautilus"), "File manager"),
    (("app.launch", "files"), "File manager"),
    (("app.launch", "file manager"), "File manager"),
    (("app.launch", "signal"), "Signal"),
    (("app.launch", "obsidian"), "Obsidian"),
    (("window.close", None), "Close window"),
    (("system.lock", None), "Lock system"),
    (("audio.mute", None), "Mute"),
    (("audio.volume", "up"), "Volume up"),
    (("audio.volume", "down"), "Volume down"),
)

_cache = {"at": 0.0, "by_description": {}}


def _runtime_cache_path():
    value = os.environ.get("XDG_RUNTIME_DIR")
    if not value or not Path(value).is_absolute():
        return None
    return Path(value) / "omarchy-voice" / "keybinds.cache"


def parse_keybind_print(text):
    """Map Super+K descriptions to the first listed chord."""
    result = {}
    if type(text) is not str or len(text) > MAX_KEYBIND_BYTES:
        return result
    for raw in text.splitlines():
        line = raw.strip()
        match = KEYBIND_LINE.fullmatch(line)
        if not match:
            continue
        chord = " ".join(match[1].split())
        description = match[2].strip()
        if "(" in description:
            description = description.split("(", 1)[0].rstrip()
        if not description or description in result:
            continue
        if not SAFE_CHORD.fullmatch(chord):
            continue
        result[description] = chord
        result[description.lower()] = chord
    return result


def load_keybinds(*, runner=subprocess.run, now=None):
    """Refresh the description→chord table from live Hyprland bindings."""
    clock = time.monotonic() if now is None else now
    cached = _cache["by_description"]
    if cached and clock - _cache["at"] < KEYBIND_TTL_SECONDS:
        return cached
    try:
        completed = runner(
            ["omarchy", "menu", "keybindings", "--print"],
            check=False,
            timeout=3,
            capture_output=True,
            text=True,
        )
        text = completed.stdout if completed.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, TypeError):
        text = ""
    parsed = parse_keybind_print(text)
    if parsed:
        _cache["at"] = clock
        _cache["by_description"] = parsed
        path = _runtime_cache_path()
        if path is not None:
            try:
                path.parent.mkdir(mode=0o700, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            except OSError:
                pass
        return parsed
    if cached:
        return cached
    path = _runtime_cache_path()
    try:
        if path is not None and path.is_file() and path.stat().st_size <= MAX_KEYBIND_BYTES:
            parsed = parse_keybind_print(path.read_text(encoding="utf-8"))
            if parsed:
                _cache["at"] = clock
                _cache["by_description"] = parsed
                return parsed
    except OSError:
        pass
    return {}


def reset_keybinds():
    _cache["at"] = 0.0
    _cache["by_description"] = {}


def _hint_key(intent):
    if not isinstance(intent, Intent):
        return None
    if intent.action == "app.launch":
        application = intent.parameters.get("application")
        if type(application) is not str:
            return None
        return (intent.action, application.lower())
    if intent.action == "audio.volume":
        direction = intent.parameters.get("direction")
        if direction not in ("up", "down"):
            return None
        return (intent.action, direction)
    if intent.action in ("window.close", "system.lock", "audio.mute"):
        return (intent.action, None)
    if intent.action == "workspace.switch":
        number = intent.parameters.get("number")
        if type(number) is not int or not 1 <= number <= 10:
            return None
        return (intent.action, number)
    if intent.action == "window.move_workspace":
        number = intent.parameters.get("number")
        if type(number) is int and 1 <= number <= 10:
            return (intent.action, number)
        return None
    return None


def _description(intent):
    key = _hint_key(intent)
    if key is None:
        return None
    if key[0] == "workspace.switch":
        return "Switch to workspace " + str(key[1])
    if key[0] == "window.move_workspace":
        return "Move window to workspace " + str(key[1])
    return dict(KEYBIND_HINTS).get(key)


def osd_message(intent, *, runner=subprocess.run, now=None, enabled=True):
    """Chord-only OSD text when Super+K has a matching bind."""
    if enabled is not True:
        return ""
    description = _description(intent)
    if description is None:
        return ""
    table = load_keybinds(runner=runner, now=now)
    chord = table.get(description) or table.get(description.lower())
    if not chord:
        return ""
    return chord[:MAX_CHORD]


def show_osd(intent, *, runner=subprocess.run, now=None, enabled=True):
    """Best-effort Omarchy OSD; skip when disabled or there is no chord."""
    message = osd_message(intent, runner=runner, now=now, enabled=enabled)
    if not message:
        return
    payload = json.dumps(
        {"icon": OSD_ICON, "message": message, "duration": OSD_DURATION_MS}
    )
    try:
        runner(
            ["omarchy-shell", "osd", "show", payload],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, TypeError):
        pass
