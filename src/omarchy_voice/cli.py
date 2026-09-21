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
from .config import load_config
from .core import VoiceError, Router, parse
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
        "stop",
        "cancel",
        "status",
        "providers",
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
        if command in ("start", "stop", "cancel", "status"):
            result = request(command)
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
