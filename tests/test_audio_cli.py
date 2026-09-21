"""Recorder and real CLI lifecycle tests without microphone/desktop access."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import Mock

import pytest
from omarchy_voice.audio import PipeWireRecorder
from omarchy_voice.core import VoiceError
from omarchy_voice.cli import transcribe_file
from omarchy_voice.config import Config


def test_recording_format_and_cleanup(tmp_path, monkeypatch):
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr("omarchy_voice.audio.subprocess.Popen", popen)
    recorder = PipeWireRecorder(tmp_path)
    recorder.start()
    argv = popen.call_args.args[0]
    assert argv[:-1] == [
        "pw-record",
        "--rate",
        "16000",
        "--channels",
        "1",
        "--format",
        "s16",
    ]
    assert recorder.path.parent == tmp_path
    assert recorder.path.stat().st_mode & 0o777 == 0o600
    recorder.path.write_bytes(b"x" * 64)
    assert recorder.stop() == recorder.path
    process.send_signal.assert_called_with(signal.SIGINT)
    recorder.cleanup()
    assert not recorder.path.exists()


def test_recorder_start_failure_removes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "omarchy_voice.audio.subprocess.Popen", Mock(side_effect=FileNotFoundError)
    )
    recorder = PipeWireRecorder(tmp_path)
    with pytest.raises(VoiceError):
        recorder.start()
    assert not list(tmp_path.iterdir())


def test_recorder_forced_kill(tmp_path, monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("pw-record", 2), 0]
    monkeypatch.setattr(
        "omarchy_voice.audio.subprocess.Popen", Mock(return_value=process)
    )
    recorder = PipeWireRecorder(tmp_path)
    recorder.start()
    recorder.cleanup()
    process.kill.assert_called_once()
    assert not recorder.path.exists()


def test_invalid_audio_never_reaches_stt(tmp_path):
    path = tmp_path / "bad.wav"
    path.write_bytes(b"invalid audio")
    with pytest.raises(VoiceError, match="WAV"):
        transcribe_file(path, Config())


def test_real_cli_daemon_roundtrip():
    # Short paths matter: Linux sockaddr_un is limited to 108 bytes.
    with tempfile.TemporaryDirectory(prefix="voice-cli-") as directory:
        # Fake only the read-only focus query; never contact the live desktop.
        hyprctl = Path(directory) / "hyprctl"
        hyprctl.write_text(
            f"#!{sys.executable}\nimport json, sys\n"
            "assert sys.argv[1:] == ['-j', 'activewindow']\n"
            "print(json.dumps({'address': '0x123abc'}))\n"
        )
        hyprctl.chmod(0o700)
        env = dict(os.environ, XDG_RUNTIME_DIR=directory,
                   PATH=directory + os.pathsep + os.environ.get("PATH", ""))
        executable = [sys.executable, "-m", "omarchy_voice"]
        process = subprocess.Popen(
            executable + ["serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        path = Path(directory) / "omarchy-voice/control.sock"
        try:
            for _ in range(200):
                if path.exists():
                    break
                if process.poll() is not None:
                    pytest.fail("daemon failed to start: " + process.communicate()[0])
                time.sleep(0.01)
            for command, state in [("status", "idle"), ("cancel", "idle")]:
                result = subprocess.run(
                    executable + [command],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                assert json.loads(result.stdout)["state"] == state
            duplicate = subprocess.run(
                executable + ["serve"],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert duplicate.returncode == 1
            assert json.loads(duplicate.stdout)["state"] == "error"
            result = subprocess.run(
                executable + ["run", "close window", "--execute"],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            pending = json.loads(result.stdout)
            assert pending["state"] == "confirmation" and pending["confirmation_token"]
            subprocess.run(
                executable + ["cancel"],
                env=env,
                capture_output=True,
                timeout=5,
                check=True,
            )
        finally:
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0 and not path.exists() and not stderr
