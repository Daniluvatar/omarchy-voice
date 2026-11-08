"""Bounded, privacy-aware diagnostic log. Transcripts stay local."""

from datetime import datetime, timezone
from pathlib import Path
import os
import stat
import tempfile

MAX_LOG_BYTES = 256 * 1024
KEEP_LINES = 400


def _state_directory():
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    if not base.is_absolute():
        raise OSError("XDG_STATE_HOME must be absolute")

    directory = base / "omarchy-voice"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise OSError("Unsafe voice state directory")
    if info.st_uid != os.getuid():
        raise OSError("Voice state directory is not owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        os.chmod(directory, 0o700)
    return directory


def _prepare_log(path):
    """Refuse symlinks/non-regular files and restrict an existing log to 0600."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return path

    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise OSError("Voice log is not a regular file")
    if info.st_uid != os.getuid():
        raise OSError("Voice log is not owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o600:
        os.chmod(path, 0o600)
    return path


def log_path():
    directory = _state_directory()
    return _prepare_log(directory / "voice.log")


def _rotate(path):
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return
    if info.st_size <= MAX_LOG_BYTES:
        return

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        handle = os.fdopen(fd, "r", encoding="utf-8", errors="replace")
        fd = None
        with handle:
            lines = handle.read().splitlines(True)
    finally:
        if fd is not None:
            os.close(fd)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".voice.log.",
        delete=False,
    )
    tmp_name = tmp.name
    try:
        os.fchmod(tmp.fileno(), 0o600)
        tmp.write("".join(lines[-KEEP_LINES:]))
        tmp.flush()
        tmp.close()
        os.replace(tmp_name, path)
    except OSError:
        try:
            tmp.close()
        except OSError:
            pass
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


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

        fd = os.open(
            path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.fchmod(fd, 0o600)
            handle = os.fdopen(fd, "a", encoding="utf-8")
            fd = None
            with handle:
                handle.write(line)
                handle.flush()
        finally:
            if fd is not None:
                os.close(fd)

        _rotate(path)
    except OSError:
        return
