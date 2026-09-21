"""Deterministic intents and a closed action boundary. No shell evaluation."""

from dataclasses import dataclass
from pathlib import Path
import configparser
import json
import os
import re
import subprocess


class VoiceError(Exception):
    """A safe, user-facing failure (never include transcript text)."""


ACTIONS = frozenset(
    {
        "app.launch",
        "window.close",
        "workspace.switch",
        "audio.volume",
        "audio.mute",
        "system.lock",
    }
)
APP = re.compile(r"[a-z0-9][a-z0-9 ._+-]{0,79}\Z")
APP_ALIASES = {
    "brave": "brave",
    "brave browser": "brave",
    "browser": "brave",
    "terminal": "terminal",
    "term": "terminal",
    "ghostty": "terminal",
    "spotify": "spotify",
}


@dataclass(frozen=True)
class Intent:
    action: str
    parameters: dict


def parse(text: str) -> Intent:
    if not isinstance(text, str) or len(text) > 512 or any(ord(c) < 32 for c in text):
        raise VoiceError("Invalid command")
    text = " ".join(text.lower().strip().split())
    # STT commonly adds a sentence terminator. Strip exactly one, never
    # punctuation inside commands or compound instructions.
    if text.endswith((".", "?", "!")):
        text = text[:-1].rstrip()
    fixed = {
        "close window": ("window.close", {}),
        "mute": ("audio.mute", {}),
        "lock computer": ("system.lock", {}),
        "volume up": ("audio.volume", {"direction": "up"}),
        "volume down": ("audio.volume", {"direction": "down"}),
    }
    if text in fixed:
        return Intent(*fixed[text])
    words = [
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
    ]
    if text.startswith("workspace "):
        value = text.removeprefix("workspace ")
        if value in words:
            return Intent("workspace.switch", {"number": words.index(value) + 1})
        if value in [str(i) for i in range(1, 11)]:
            return Intent("workspace.switch", {"number": int(value)})
    match = re.fullmatch(r"(?:open|launch|start) (.+)", text)
    if match and APP.fullmatch(match[1]) and ".." not in match[1]:
        application = APP_ALIASES.get(match[1], match[1])
        return Intent("app.launch", {"application": application})
    raise VoiceError("Command not recognized")


class DesktopRegistry:
    """Resolve exact installed desktop IDs or Name fields, never Exec strings."""

    def __init__(self, roots=None, aliases=None):
        if roots is None:
            roots = [
                Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
                / "applications"
            ]
            roots += [
                Path(p) / "applications"
                for p in os.environ.get(
                    "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
                ).split(":")
                if p.startswith("/")
            ]
        self.roots = [Path(p) for p in roots]
        self.aliases = aliases or {}

    def resolve(self, name):
        target = self.aliases.get(name, name).lower()
        matches = []
        seen = set()
        for root in self.roots:
            if not root.is_absolute():
                continue
            for path in sorted(root.glob("**/*.desktop")):
                ident = str(path.relative_to(root)).replace("/", "-").lower()
                if ident in seen:
                    continue
                seen.add(ident)
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    info = path.stat()
                    if (
                        info.st_size > 65536
                        or info.st_uid not in (0, os.getuid())
                        or info.st_mode & 0o022
                    ):
                        continue
                    parser.read(path, encoding="utf-8")
                    entry = parser["Desktop Entry"]
                    if (
                        entry.get("Type") != "Application"
                        or entry.get("Hidden", "false").lower() == "true"
                        or entry.get("NoDisplay", "false").lower() == "true"
                    ):
                        continue
                    if (
                        not entry.get("Exec")
                        and entry.get("DBusActivatable", "false").lower() != "true"
                    ):
                        continue
                    if target in (ident, entry.get("Name", "").lower()):
                        matches.append(path.absolute())
                except (OSError, UnicodeError, configparser.Error, KeyError):
                    continue
        if len(matches) != 1:
            raise VoiceError(f"Application '{name}' is unavailable or ambiguous")
        return matches[0]


class Router:
    def __init__(self, config, registry=None, runner=subprocess.run):
        self.config = config
        self.registry = registry or DesktopRegistry(aliases=config.aliases)
        self.runner = runner

    @staticmethod
    def validate_window(address):
        if (type(address) is not str
                or re.fullmatch(r"0x[0-9a-fA-F]{1,16}", address) is None
                or int(address, 16) == 0):
            raise VoiceError("No valid original window to close")
        return address

    def capture_window(self):
        """Snapshot focus before capture/confirmation UI can change it."""
        try:
            result = self.runner(
                ["hyprctl", "-j", "activewindow"], check=True, timeout=2,
                capture_output=True, text=True,
            )
            data = json.loads(result.stdout)
            if type(data) is not dict:
                raise ValueError()
            return self.validate_window(data.get("address"))
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError) as exc:
            raise VoiceError("Cannot identify original window") from exc

    def plan(self, intent, *, window_address=None):
        if not isinstance(intent, Intent) or type(intent.action) is not str:
            raise VoiceError("Invalid intent")
        a, p = intent.action, intent.parameters
        if a not in ACTIONS or a not in self.config.permissions or type(p) is not dict:
            raise VoiceError("Action not permitted")
        keys = {
            "app.launch": {"application"},
            "workspace.switch": {"number"},
            "audio.volume": {"direction"},
        }.get(a, set())
        if set(p) != keys:
            raise VoiceError("Invalid action parameters")
        if a == "app.launch":
            value = p["application"]
            if type(value) is not str or not APP.fullmatch(value) or ".." in value:
                raise VoiceError("Invalid application")
            # Spoken "terminal" uses Omarchy's default terminal. A configured
            # terminal alias still launches that desktop file instead.
            if value == "terminal" and "terminal" not in self.config.aliases:
                return ["omarchy", "launch", "terminal"]
            return ["gio", "launch", str(self.registry.resolve(value))]
        if a == "workspace.switch":
            if type(p["number"]) is not int or not 1 <= p["number"] <= 10:
                raise VoiceError("Invalid workspace")
            return ["hyprctl", "dispatch", "workspace", str(p["number"])]
        if a == "audio.volume":
            if type(p["direction"]) is not str or p["direction"] not in ("up", "down"):
                raise VoiceError("Invalid volume direction")
            return [
                "wpctl",
                "set-volume",
                "-l",
                "1.0",
                "@DEFAULT_AUDIO_SINK@",
                "5%+" if p["direction"] == "up" else "5%-",
            ]
        if a == "window.close":
            # An unbound plan is preview-only, never executable.
            target = (self.validate_window(window_address)
                      if window_address is not None else "<original-window>")
            return ["hyprctl", "dispatch", "closewindow", "address:" + target]
        return {
            "audio.mute": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
            "system.lock": ["omarchy", "system", "lock"],
        }[a]

    def execute(self, intent, *, confirmed=False, window_address=None):
        argv = self.plan(intent, window_address=window_address)
        if intent.action == "window.close":
            if confirmed is not True:
                raise VoiceError("Explicit confirmation required")
            self.validate_window(window_address)
        try:
            self.runner(
                argv,
                check=True,
                timeout=10,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VoiceError("Desktop action failed") from exc
