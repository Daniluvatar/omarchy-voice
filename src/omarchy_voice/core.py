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
        "window.move_monitor",
        "window.move_workspace",
        "workspace.switch",
        "audio.volume",
        "audio.mute",
        "system.lock",
    }
)
WINDOW_ADDRESS = re.compile(r"0x[0-9a-fA-F]{1,16}\Z")
MONITOR_DIRECTIONS = ("left", "right", "other")
WORKSPACE_WORDS = (
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
)
MOVE_MONITOR = re.compile(
    r"\Amove(?:\s+(?:this|it)(?:\s+window)?|\s+(?:the\s+)?window)"
    r"(?:\s+to(?:\s+the)?)?\s+(left|right|other)"
    r"(?:\s+(?:screen|monitor|display))?\Z"
)
MOVE_TO_WORKSPACE = re.compile(
    r"\A(?:switch|move)"
    r"(?:\s+(?:this|it)(?:\s+window)?|\s+(?:the\s+)?window)?"
    r"\s+to(?:\s+the)?"
    r"\s+workspace\s+"
    r"(one|two|three|four|five|six|seven|eight|nine|ten|[1-9]|10)\Z"
)
MOVE_WORKSPACE_SIDE = re.compile(
    r"\A(?:switch|move)"
    r"(?:\s+(?:this|it)(?:\s+window)?|\s+(?:the\s+)?window)?"
    r"\s+to(?:\s+the)?"
    r"\s+(?:(left|right|previous|next)\s+workspace|workspace\s+(left|right|previous|next))\Z"
)
APP = re.compile(r"[a-z0-9][a-z0-9 ._+-]{0,79}\Z")
APP_ALIASES = {
    "brave": "brave",
    "brave browser": "brave",
    "browser": "brave",
    "chromium": "brave",
    "terminal": "terminal",
    "term": "terminal",
    "termina": "terminal",
    "terminator": "terminal",
    "ghostty": "terminal",
    "spotify": "spotify",
}


def _workspace_number(value):
    if type(value) is not str:
        return None
    if value in WORKSPACE_WORDS:
        return WORKSPACE_WORDS.index(value) + 1
    if value in [str(i) for i in range(1, 11)]:
        return int(value)
    return None


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
    # tiny.en often inserts a comma after Open: "Open, brave."
    text = text.replace(",", " ")
    text = re.sub(r"\bwork\s+space\b", "workspace", text)
    text = " ".join(text.split())
    # A missed PTT release records the same command twice.
    if ". " in text:
        first, rest = text.split(". ", 1)
        if first == rest.rstrip(".?!"):
            text = first
    fixed = {
        "close window": ("window.close", {}),
        "mute": ("audio.mute", {}),
        "lock computer": ("system.lock", {}),
        "volume up": ("audio.volume", {"direction": "up"}),
        "volume down": ("audio.volume", {"direction": "down"}),
    }
    if text in fixed:
        return Intent(*fixed[text])
    move = MOVE_MONITOR.fullmatch(text)
    if move:
        return Intent("window.move_monitor", {"direction": move[1]})
    numbered = MOVE_TO_WORKSPACE.fullmatch(text)
    if numbered:
        number = _workspace_number(numbered[1])
        if number is None:
            raise VoiceError("Command not recognized")
        return Intent("window.move_workspace", {"number": number})
    side = MOVE_WORKSPACE_SIDE.fullmatch(text)
    if side:
        label = side[1] or side[2]
        direction = "left" if label in ("left", "previous") else "right"
        return Intent("window.move_workspace", {"direction": direction})
    if text.startswith("workspace "):
        value = text.removeprefix("workspace ")
        number = _workspace_number(value)
        if number is not None:
            return Intent("workspace.switch", {"number": number})
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
        if (
            type(address) is not str
            or WINDOW_ADDRESS.fullmatch(address) is None
            or int(address, 16) == 0
        ):
            raise VoiceError("No valid original window")
        return address

    @staticmethod
    def lua_window_ref(address):
        Router.validate_window(address)
        return 'hl.get_window("address:' + address + '")'

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
        if a == "window.move_workspace":
            if set(p) not in ({"number"}, {"direction"}):
                raise VoiceError("Invalid action parameters")
        else:
            keys = {
                "app.launch": {"application"},
                "workspace.switch": {"number"},
                "audio.volume": {"direction"},
                "window.move_monitor": {"direction"},
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
            return [
                "hyprctl",
                "dispatch",
                'hl.dsp.focus({workspace="' + str(p["number"]) + '"})',
            ]
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
            if window_address is None:
                return [
                    "hyprctl",
                    "dispatch",
                    'hl.dsp.window.close({window=hl.get_window("address:<original-window>")})',
                ]
            return [
                "hyprctl",
                "dispatch",
                "hl.dsp.window.close({window="
                + self.lua_window_ref(window_address)
                + "})",
            ]
        if a == "window.move_monitor":
            if type(p["direction"]) is not str or p["direction"] not in MONITOR_DIRECTIONS:
                raise VoiceError("Invalid monitor direction")
            if window_address is None:
                return [
                    "hyprctl",
                    "dispatch",
                    'hl.dsp.window.move({monitor="<monitor>", window=hl.get_window("address:<original-window>")})',
                ]
            return self._move_monitor_argv(p["direction"], window_address)
        if a == "window.move_workspace":
            if window_address is None:
                return [
                    "hyprctl",
                    "dispatch",
                    'hl.dsp.window.move({workspace="<workspace>", window=hl.get_window("address:<original-window>")})',
                ]
            return self._move_workspace_argv(p, window_address)
        return {
            "audio.mute": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
            "system.lock": ["omarchy", "system", "lock"],
        }[a]

    def _move_monitor_argv(self, direction, window_address):
        address = self.validate_window(window_address)
        current = self._client(address)
        if type(current.get("monitor")) is not int:
            raise VoiceError("Original window is gone")
        monitors = self._hypr_json("monitors")
        if type(monitors) is not list:
            raise VoiceError("Cannot read window layout")
        layout = []
        seen = set()
        for monitor in monitors:
            if type(monitor) is not dict:
                continue
            ident = monitor.get("id")
            name = monitor.get("name")
            xpos = monitor.get("x")
            if type(ident) is not int or type(name) is not str:
                continue
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", name):
                continue
            if not isinstance(xpos, (int, float)) or isinstance(xpos, bool) or ident in seen:
                continue
            xpos_value = float(xpos)
            seen.add(ident)
            layout.append((xpos_value, ident, name))
        layout.sort()
        names = [item[2] for item in layout]
        current_name = None
        for _x, ident, name in layout:
            if ident == current["monitor"]:
                current_name = name
                break
        if current_name is None or not names:
            raise VoiceError("Cannot identify original monitor")
        if direction == "left":
            target = names[0]
        elif direction == "right":
            target = names[-1]
        else:
            if len(names) != 2:
                raise VoiceError("Need exactly two monitors for other screen")
            target = names[0] if current_name == names[1] else names[1]
        if target == current_name:
            raise VoiceError("Window is already on that screen")
        return [
            "hyprctl",
            "dispatch",
            "hl.dsp.window.move({monitor=\""
            + target
            + "\", window="
            + self.lua_window_ref(address)
            + "})",
        ]

    def _move_workspace_argv(self, parameters, window_address):
        address = self.validate_window(window_address)
        if set(parameters) == {"number"}:
            number = parameters["number"]
            if type(number) is not int or not 1 <= number <= 10:
                raise VoiceError("Invalid workspace")
            return self._window_move_workspace_argv(address, number)
        if set(parameters) != {"direction"} or parameters["direction"] not in (
            "left",
            "right",
        ):
            raise VoiceError("Invalid workspace direction")
        current = self._client(address)
        workspace = current.get("workspace")
        ident = workspace.get("id") if type(workspace) is dict else workspace
        if type(ident) is not int or not 1 <= ident <= 10:
            raise VoiceError("Cannot identify original workspace")
        target = ident - 1 if parameters["direction"] == "left" else ident + 1
        if not 1 <= target <= 10:
            raise VoiceError("No workspace in that direction")
        return self._window_move_workspace_argv(address, target)

    def _window_move_workspace_argv(self, address, number):
        return [
            "hyprctl",
            "dispatch",
            'hl.dsp.window.move({workspace="'
            + str(number)
            + '", window='
            + self.lua_window_ref(address)
            + "})",
        ]

    def _client(self, address):
        clients = self._hypr_json("clients")
        if type(clients) is not list:
            raise VoiceError("Cannot read window layout")
        for client in clients:
            if type(client) is dict and client.get("address") == address:
                return client
        raise VoiceError("Original window is gone")

    def _hypr_json(self, command):
        try:
            result = self.runner(
                ["hyprctl", "-j", command],
                check=True,
                timeout=2,
                capture_output=True,
                text=True,
            )
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise VoiceError("Cannot read window layout") from exc

    def execute(self, intent, *, confirmed=False, window_address=None):
        argv = self.plan(intent, window_address=window_address)
        if intent.action == "window.close":
            if confirmed is not True:
                raise VoiceError("Explicit confirmation required")
            self.validate_window(window_address)
        if intent.action in ("window.move_monitor", "window.move_workspace"):
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
