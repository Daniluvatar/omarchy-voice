"""Bounded, privacy-aware diagnostic log. Transcripts stay local."""

from datetime import datetime, timezone
from pathlib import Path
import os


def log_path():
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    if not base.is_absolute():
        raise OSError("XDG_STATE_HOME must be absolute")
    directory = base / "omarchy-voice"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "voice.log"


def write_log(level, event, **fields):
    try:
        path = log_path()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = [f"{stamp} {level} {event}"]
        for key, value in fields.items():
            if value is None:
                continue
            text = " ".join(str(value).split())
            if len(text) > 240:
                text = text[:240]
            parts.append(f"{key}={text}")
        line = " ".join(parts) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
        if path.stat().st_size > 256 * 1024:
            data = path.read_text(encoding="utf-8").splitlines(True)[-400:]
            path.write_text("".join(data), encoding="utf-8")
    except OSError:
        return
