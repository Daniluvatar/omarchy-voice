"""Security/lifecycle regressions; never invoke a desktop action."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import pytest
from omarchy_voice.config import Config, load_config
from omarchy_voice.core import VoiceError, Router, DesktopRegistry
from omarchy_voice.providers import IsolatedSTT, FasterWhisper
from omarchy_voice.service import (
    Controller,
    Server,
    dispatch,
    request,
    runtime_dir,
    _receive,
)
from test_core import Recorder, Worker, controller, wait


def test_late_result_cannot_act(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class SlowWorker(Worker):
        def transcribe(self, *args):
            entered.set()
            release.wait(2)
            return "mute"

    worker = SlowWorker()
    c = Controller(
        Config(),
        recorder_factory=lambda: Recorder(tmp_path / "audio"),
        worker_factory=lambda: worker,
        router=Router(Config(), runner=lambda *a, **k: calls.append(a)),
    )
    c.router.capture_window = lambda: "0x123abc"
    c.start()
    c.stop()
    assert entered.wait(1)
    c.cancel()
    release.set()
    c.thread.join(2)
    assert not calls and c.status()["state"] == "idle" and worker.closed
    c.close()


def test_recording_limit(tmp_path):
    c, calls = controller(tmp_path, max_seconds=0.02)
    c.start()
    for _ in range(100):
        if c.status()["state"] == "error":
            break
        time.sleep(0.01)
    assert c.status()["state"] == "error"
    assert not (tmp_path / "audio.wav").exists() and not calls
    c.close()


def test_confirmation_expiry(tmp_path):
    c, calls = controller(tmp_path, "close window", confirmation_seconds=0.02)
    c.start()
    c.stop()
    wait(c)
    token = c.status()["confirmation_token"]
    time.sleep(0.03)
    with pytest.raises(VoiceError):
        c.confirm(token)
    assert not calls and c.status()["state"] == "idle"
    c.close()


def test_confirmation_cancel(tmp_path):
    c, calls = controller(tmp_path, "close window")
    c.run("close window")
    with pytest.raises(VoiceError):
        c.confirm("é")
    token = c.status()["confirmation_token"]
    c.cancel()
    with pytest.raises(VoiceError):
        c.confirm(token)
    assert not calls
    c.close()


def test_duplicate_start_and_stop(tmp_path):
    c, _ = controller(tmp_path)
    with pytest.raises(VoiceError):
        c.stop()
    c.start()
    with pytest.raises(VoiceError):
        c.start()
    c.close()
    assert not (tmp_path / "audio.wav").exists()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"command": []},
        {"command": "power"},
        {"command": "status", "extra": True},
        {"command": "run", "text": 12},
        {"command": "confirm", "token": 12},
    ],
)
def test_ipc_schema(tmp_path, payload):
    c, _ = controller(tmp_path)
    with pytest.raises(VoiceError):
        dispatch(c, payload)
    c.close()


@pytest.mark.parametrize(
    "payload",
    [
        b"[]\n",
        b"invalid\n",
        b"x" * 4097,
        b"[" * 1500 + b"]" * 1500 + b"\n",
        b"{}\n{}\n",
    ],
)
def test_bounded_wire(payload):
    a, b = socket.socketpair()
    try:
        a.sendall(payload)
        with pytest.raises(VoiceError):
            _receive(b)
    finally:
        a.close()
        b.close()


def test_runtime_symlink(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    (tmp_path / "target").mkdir()
    (tmp_path / "omarchy-voice").symlink_to(tmp_path / "target")
    with pytest.raises(VoiceError):
        runtime_dir()


@pytest.fixture
def short_runtime():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="voice-") as directory:
        yield Path(directory)


def test_server_ipc_and_duplicate_lock(short_runtime, monkeypatch):
    tmp_path = short_runtime
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    c, calls = controller(tmp_path)
    server = Server(c)
    thread = threading.Thread(target=server.serve)
    thread.start()
    path = tmp_path / "omarchy-voice/control.sock"
    try:
        for _ in range(100):
            if path.exists():
                break
            time.sleep(0.01)
        assert path.stat().st_mode & 0o777 == 0o600
        assert request("status")["state"] == "idle"
        assert request("start")["state"] == "listening"
        assert request("cancel")["state"] == "idle"
        second, _ = controller(tmp_path)
        with pytest.raises(VoiceError, match="already running"):
            Server(second).serve()
        assert request("status")["state"] == "idle"
        assert request("run", text="close window")["state"] == "confirmation"
        assert request("cancel")["state"] == "idle" and not calls
    finally:
        server.stop_event.set()
        thread.join(3)
    assert not thread.is_alive() and not path.exists()


def test_cli_default_dry_run():
    result = subprocess.run(
        [sys.executable, "-m", "omarchy_voice", "run", "volume up"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["dry_run"] and data["argv"][0] == "wpctl"
    result = subprocess.run(
        [sys.executable, "-m", "omarchy_voice", "parse", "open brave; reboot"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and json.loads(result.stdout)["state"] == "error"
    assert "brave" not in result.stdout


def test_provider_lazy_and_offline(monkeypatch, tmp_path):
    import types

    imported = []

    class Model:
        def __init__(self, *args, **kwargs):
            imported.append(kwargs)

        def transcribe(self, *args, **kwargs):
            return ([types.SimpleNamespace(text="mute")], None)

    monkeypatch.setitem(
        sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model)
    )
    monkeypatch.setattr(FasterWhisper, "available", lambda _: True)
    assert FasterWhisper(Config()).transcribe(tmp_path / "audio.wav", "en") == "mute"
    assert imported == [
        {"device": "cpu", "compute_type": "int8", "local_files_only": True}
    ]


def test_worker_failure_is_bounded(tmp_path):
    # Missing file/dependency/model: real isolated process, no network or fake output.
    worker = IsolatedSTT(Config(timeout_seconds=2))
    with pytest.raises(VoiceError):
        worker.transcribe(tmp_path / "missing.wav", "en", threading.Event())
    assert worker.process is not None and not worker.process.is_alive()


def test_worker_precancelled(tmp_path):
    worker = IsolatedSTT(Config())
    worker.cancel()
    with pytest.raises(VoiceError):
        worker.transcribe(tmp_path / "audio", "en", threading.Event())
    assert worker.process is None


def test_hidden_user_override_masks_system(tmp_path):
    user = tmp_path / "user"
    system = tmp_path / "system"
    user.mkdir()
    system.mkdir()
    (user / "app.desktop").write_text("[Desktop Entry]\nHidden=true\n")
    (system / "app.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=App\nExec=app\n"
    )
    with pytest.raises(VoiceError):
        DesktopRegistry([user, system], {}).resolve("app")


def test_untrusted_desktop_file(tmp_path):
    path = tmp_path / "app.desktop"
    path.write_text("[Desktop Entry]\nType=Application\nName=App\nExec=app\n")
    path.chmod(0o666)
    with pytest.raises(VoiceError):
        DesktopRegistry([tmp_path], {}).resolve("app")


def blocked_worker(*args):
    time.sleep(10)


def test_stt_timeout_kills_process(tmp_path, monkeypatch):
    import omarchy_voice.providers as providers

    monkeypatch.setattr(providers, "_child", blocked_worker)
    worker = IsolatedSTT(Config(timeout_seconds=0.05))
    with pytest.raises(VoiceError, match="timed out"):
        worker.transcribe(tmp_path / "audio", "en", threading.Event())
    assert not worker.process.is_alive()


def test_stt_cancel_kills_process(tmp_path, monkeypatch):
    import omarchy_voice.providers as providers

    monkeypatch.setattr(providers, "_child", blocked_worker)
    worker = IsolatedSTT(Config(timeout_seconds=5))
    event = threading.Event()
    errors = []

    def work():
        try:
            worker.transcribe(tmp_path / "audio", "en", event)
        except VoiceError as exc:
            errors.append(exc)

    thread = threading.Thread(target=work)
    thread.start()
    for _ in range(100):
        if worker.process is not None and worker.process.pid is not None:
            break
        time.sleep(0.01)
    event.set()
    worker.cancel()
    thread.join(2)
    assert errors and not thread.is_alive() and not worker.process.is_alive()


def test_config_example():
    config = load_config(Path(__file__).parents[1] / "examples/config.toml")
    assert config.provider == "faster-whisper" and config.compute_type == "int8"


@pytest.mark.parametrize(
    "content",
    [
        "[stt]\ndevice=[]",
        "[stt]\nmodel=12",
        "[audio]\nmax_seconds=true",
        "[audio]\nmax_seconds=nan",
        "[notifications]\nenabled=1",
        '[applications.aliases]\nbrave="/bin/sh"',
        '[permissions]\nallow="audio.mute"',
    ],
)
def test_wrong_config_types(tmp_path, content):
    path = tmp_path / "bad.toml"
    path.write_text(content)
    with pytest.raises(VoiceError):
        load_config(path)
