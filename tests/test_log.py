import os
import stat

import pytest

from omarchy_voice.cli import main
from omarchy_voice.log import KEEP_LINES, MAX_LOG_BYTES, log_path, write_log


def test_log_records_transcript(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    write_log(
        "ERROR",
        "process-failed",
        text="open term",
        error="Application 'term' is unavailable or ambiguous",
    )
    path = log_path()
    content = path.read_text()
    assert "open term" in content
    assert "unavailable" in content
    assert main(["logs"]) == 0
    output = capsys.readouterr().out
    assert str(path) in output
    assert "open term" in output


def test_fresh_log_and_state_directory_are_private(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    previous_umask = os.umask(0o022)
    try:
        write_log("INFO", "transcribed", text="private speech")
    finally:
        os.umask(previous_umask)

    path = log_path()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_existing_permissive_log_is_restricted(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    directory = tmp_path / "omarchy-voice"
    directory.mkdir(mode=0o755)
    path = directory / "voice.log"
    path.write_text("existing\n", encoding="utf-8")
    path.chmod(0o644)

    write_log("INFO", "transcribed", text="private speech")

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "existing" in path.read_text(encoding="utf-8")


def test_log_symlink_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    directory = tmp_path / "omarchy-voice"
    directory.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("secret", encoding="utf-8")
    path = directory / "voice.log"
    path.symlink_to(target)

    with pytest.raises(OSError):
        log_path()

    write_log("INFO", "transcribed", text="must not reach the target")
    assert target.read_text(encoding="utf-8") == "secret"


def test_state_directory_symlink_is_refused(tmp_path, monkeypatch):
    base = tmp_path / "state"
    base.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (base / "omarchy-voice").symlink_to(target)
    monkeypatch.setenv("XDG_STATE_HOME", str(base))

    with pytest.raises(OSError):
        log_path()


def test_rotation_keeps_recent_lines_and_private_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    directory = tmp_path / "omarchy-voice"
    directory.mkdir()
    path = directory / "voice.log"
    path.write_text(
        "".join(f"old-{i:05d}-{'x' * 70}\n" for i in range(4000)),
        encoding="utf-8",
    )
    path.chmod(0o644)
    assert path.stat().st_size > MAX_LOG_BYTES

    write_log("INFO", "transcribed", text="latest")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == KEEP_LINES
    assert lines[-1].endswith("text=latest")
    assert not any(line.startswith("old-00000") for line in lines)
