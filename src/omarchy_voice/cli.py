"""JSON CLI. Dry-run is the default; execution is routed through the daemon."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import signal
import sys
import threading
import wave
from .voice_commands import read_settings, read_voice_commands, remove_voice_command, set_keybind_osd, set_voice_command, update_voice_command, voice_commands_revision
from .config import load_config, set_stt, stt_options, stt_snapshot
from .core import BUILTIN_APP_NAMES, DesktopRegistry, ROLE_LAUNCH, VoiceError, Router, default_browser_desktop_id, parse
from .log import log_path
from .providers import FasterWhisper, IsolatedSTT, download_model
from .service import Controller, Server, request, runtime_dir


def parser():
    p = argparse.ArgumentParser(prog="omarchy-voice")
    p.add_argument("--config", type=Path, help="Explicit TOML configuration path")
    sub = p.add_subparsers(dest="command", required=True)
    for command in (
        "serve",
        "start",
        "start-voice-command",
        "start-alias",  # Pre-rename CLI verb; same behavior as start-voice-command.
        "stop",
        "cancel",
        "status",
        "providers",
        "apps",
        "doctor",
        "download-model",
        "logs",
    ):
        sub.add_parser(command)
    confirm = sub.add_parser("confirm")
    confirm.add_argument("token")
    for command in ("parse", "run"):
        sp = sub.add_parser(command)
        sp.add_argument("text")
        if command == "run":
            sp.add_argument("--execute", action="store_true")
    sp = sub.add_parser("transcribe")
    sp.add_argument("file", type=Path)
    sp.add_argument("--execute", action="store_true")
    for group in ("voice-command", "alias"):
        group_parser = sub.add_parser(
            group,
            help="Manage saved voice commands (the alias subcommand is a compatibility name)",
        )
        group_commands = group_parser.add_subparsers(dest="command_operation", required=True)
        group_commands.add_parser("list")
        add = group_commands.add_parser("set")
        add.add_argument("phrase")
        add.add_argument("application")
        update = group_commands.add_parser("update")
        update.add_argument("old_phrase")
        update.add_argument("new_phrase")
        update.add_argument("application")
        remove = group_commands.add_parser("remove")
        remove.add_argument("phrase")
    settings = sub.add_parser("settings")
    settings_commands = settings.add_subparsers(dest="settings_command", required=True)
    settings_commands.add_parser("show")
    keybind = settings_commands.add_parser("keybind-osd")
    keybind.add_argument("enabled", choices=("on", "off"))
    stt = settings_commands.add_parser("stt")
    stt.add_argument("key", choices=("provider", "model", "device", "language"))
    stt.add_argument("value")
    return p


def dry_run(text, config):
    intent = parse(text)
    return {
        "state": "idle",
        "message": "Dry run; no action executed",
        "dry_run": True,
        "intent": asdict(intent),
        "argv": Router(config).plan(intent),
        "requires_confirmation": intent.action == "window.close",
    }


def app_catalog(config, default_browser=None):
    """Show only installed apps and launch phrases that the router can plan."""
    registry = DesktopRegistry(voice_commands=config.voice_commands)
    apps = registry.applications()
    by_id = {app["id"]: app for app in apps}
    for app in apps:
        app["commands"] = []
    router = Router(config, registry=registry)
    if default_browser is None and "browser" not in config.voice_commands:
        default_browser = default_browser_desktop_id()
    for name in sorted(set(BUILTIN_APP_NAMES) | set(config.voice_commands)):
        phrase = "open " + name
        try:
            argv = router.plan(parse(phrase))
        except VoiceError:
            continue
        if argv == ROLE_LAUNCH["browser"]:
            app = by_id.get(default_browser)
            if app is not None:
                app["commands"].append(phrase)
            continue
        if argv[:2] == ["gio", "launch"] and len(argv) == 3:
            for root in registry.roots:
                try:
                    ident = str(Path(argv[2]).relative_to(root)).replace("/", "-")
                except ValueError:
                    continue
                app = by_id.get(ident)
                if app is not None:
                    app["commands"].append(phrase)
                break
    return apps

def transcribe_file(path, config):
    try:
        if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            raise VoiceError("Audio file is missing or too large")
        with wave.open(str(path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            if duration <= 0 or duration > config.max_seconds:
                raise VoiceError("Audio duration exceeds recording limit")
    except (OSError, wave.Error, EOFError, ZeroDivisionError) as exc:
        raise VoiceError("Expected a valid PCM WAV file") from exc
    worker = IsolatedSTT(config)
    try:
        return worker.transcribe(path, config.language, threading.Event())
    finally:
        worker.cancel()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        command = args.command
        if command == "serve":
            server = Server(Controller(config))

            def shutdown(*_):
                server.stop_event.set()

            signal.signal(signal.SIGTERM, shutdown)
            signal.signal(signal.SIGINT, shutdown)
            server.serve()
            return 0
        if command in ("start", "start-alias", "start-voice-command", "stop", "cancel", "status"):
            if command == "start-alias":
                command = "start-voice-command"
            result = request(command.replace("-", "_"))
        elif command in ("alias", "voice-command"):
            operation = args.command_operation
            if operation == "list":
                result = {"state": "idle", "message": "Configured voice commands", "voice_commands": read_voice_commands()}
            elif operation == "set":
                phrase, desktop_id = set_voice_command(args.phrase, args.application, config)
                result = {"state": "idle", "message": "Voice command saved; restart voice service to apply", "phrase": phrase, "desktop_id": desktop_id}
            elif operation == "update":
                phrase, desktop_id = update_voice_command(args.old_phrase, args.new_phrase, args.application, config)
                result = {"state": "idle", "message": "Voice command updated; restart voice service to apply", "phrase": phrase, "desktop_id": desktop_id}
            else:
                phrase = remove_voice_command(args.phrase)
                result = {"state": "idle", "message": "Voice command removed; restart voice service to apply", "phrase": phrase}
        elif command == "settings":
            if args.settings_command == "show":
                result = {
                    "state": "idle",
                    "message": "Voice settings",
                    **read_settings(),
                    "stt": stt_snapshot(config),
                    "stt_options": stt_options(config),
                }
            elif args.settings_command == "keybind-osd":
                enabled = set_keybind_osd(args.enabled == "on")
                result = {
                    "state": "idle",
                    "message": "Keybind OSD " + ("on" if enabled else "off"),
                    "keybind_osd": enabled,
                }
            else:
                snapshot = set_stt(args.key, args.value, path=args.config)
                applied = load_config(args.config)
                result = {
                    "state": "idle",
                    "message": "STT setting saved; restart voice service to apply",
                    "stt": snapshot,
                    "stt_options": stt_options(applied),
                }
        elif command == "confirm":
            result = request("confirm", token=args.token)
        elif command == "parse":
            result = {
                "state": "idle",
                "message": "Command parsed",
                "intent": asdict(parse(args.text)),
            }
        elif command == "run":
            result = (
                request("run", text=args.text)
                if args.execute
                else dry_run(args.text, config)
            )
        elif command == "transcribe":
            text = transcribe_file(args.file, config)
            result = (
                request("run", text=text) if args.execute else dry_run(text, config)
            )
        elif command == "providers":
            provider = FasterWhisper(config)
            result = {
                "state": "idle",
                "message": "Local providers",
                "providers": [
                    {
                        "name": "faster-whisper",
                        "available": provider.available(),
                        "capabilities": provider.capabilities(),
                    }
                ],
            }
        elif command == "apps":
            result = {
                "state": "idle",
                "message": "Installed applications",
                "apps": app_catalog(config),
                "voice_commands_revision": voice_commands_revision(config.voice_commands),
            }
        elif command == "doctor":
            checks = {
                name: shutil.which(name) is not None
                for name in ("pw-record", "hyprctl", "wpctl", "gio", "omarchy")
            }
            checks["stt_dependency"] = FasterWhisper(config).available()
            try:
                runtime_dir()
                checks["runtime_directory"] = True
            except VoiceError:
                checks["runtime_directory"] = False
            result = {
                "state": "idle" if all(checks.values()) else "error",
                "message": "Dependency checks (model availability is checked during offline transcription)",
                "checks": checks,
            }
        elif command == "download-model":
            location = download_model(config)
            result = {"state": "idle", "message": "Model downloaded", "path": location}
        elif command == "logs":
            path = log_path()
            try:
                lines = path.read_text(encoding="utf-8").splitlines()[-80:]
            except FileNotFoundError:
                lines = []
            except OSError as exc:
                raise VoiceError("Cannot read voice log") from exc
            result = {
                "state": "idle",
                "message": "Recent local voice log lines",
                "path": str(path),
                "lines": lines,
            }
        print(json.dumps(result))
        return 1 if result.get("state") == "error" else 0
    except VoiceError as exc:
        print(json.dumps({"state": "error", "message": str(exc)}))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"state": "error", "message": "Cancelled"}))
        return 130
    except OSError:
        print(
            json.dumps(
                {"state": "error", "message": "Operating system operation failed"}
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
