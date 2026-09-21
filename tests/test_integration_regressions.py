"""Backend/plugin contract regressions; all desktop operations are fake."""
import json
import threading
import time
from types import SimpleNamespace

import pytest

from omarchy_voice.config import Config
from omarchy_voice.core import Router, VoiceError, parse
from omarchy_voice.service import Server, request
from test_core import controller, wait
from test_security import short_runtime


@pytest.mark.parametrize("address", [None, "", "0x0", "0x0000", "0xabc;killactive", "0xabc\n", "address:0xabc", "0x" + "a" * 17, 123, True])
def test_close_address_fail_closed(address):
    router = Router(Config(), runner=lambda *a, **k: pytest.fail("executed"))
    with pytest.raises(VoiceError):
        router.execute(parse("close window"), confirmed=True, window_address=address)


@pytest.mark.parametrize("payload", ["{}", "[]", "not json", '{"address":"0x0"}', '{"address":"0x123;exec"}'])
def test_invalid_focus_query(payload):
    router = Router(Config(), runner=lambda *a, **k: SimpleNamespace(stdout=payload))
    with pytest.raises(VoiceError):
        router.capture_window()


@pytest.mark.parametrize("voice", [False, True])
def test_close_keeps_original_focus(tmp_path, voice):
    c, _ = controller(tmp_path, "close window")
    active = "0x123abc"
    calls = []

    def runner(argv, **kwargs):
        if argv == ["hyprctl", "-j", "activewindow"]:
            return SimpleNamespace(stdout=json.dumps({"address": active}))
        calls.append(argv)

    c.router.runner = runner
    try:
        if voice:
            c.start()
            active = "0x456def"  # focus changed during recording/STT
            c.stop()
            wait(c)
        else:
            c.run("close window")
        token = c.status()["confirmation_token"]
        active = "0x999aaa"  # confirmation popup acquired focus
        assert c.confirm(token)["state"] == "executing"
        wait(c)
        assert calls == [["hyprctl", "dispatch", "closewindow", "address:0x123abc"]]
    finally:
        c.close()


def test_missing_focus_does_not_fall_back_to_later_focus(tmp_path):
    c, calls = controller(tmp_path, "close window")
    c.router.capture_window = lambda: None
    c.start()
    c.router.capture_window = lambda: "0x999aaa"
    c.stop()
    wait(c)
    assert c.status()["state"] == "error" and not calls
    c.close()


@pytest.mark.parametrize("mode", ["run", "voice", "confirm"])
def test_execution_observable_over_ipc(short_runtime, monkeypatch, mode):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short_runtime))
    c, _ = controller(short_runtime)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    c.router.capture_window = lambda: "0x123abc"

    def runner(argv, **kwargs):
        calls.append(argv)
        entered.set()
        assert release.wait(3), "test did not release action"

    c.router.runner = runner
    server = Server(c)
    thread = threading.Thread(target=server.serve)
    thread.start()
    try:
        for _ in range(100):
            try:
                if request("status")["state"] == "idle":
                    break
            except VoiceError:
                pass
            time.sleep(0.01)
        else:
            pytest.fail("server did not become ready")
        if mode == "confirm":
            status = request("run", text="close window")
            result = request("confirm", token=status["confirmation_token"])
            assert result["state"] == "executing"
        elif mode == "voice":
            request("start")
            request("stop")
        else:
            assert request("run", text="mute")["state"] == "executing"
        assert entered.wait(1)
        assert request("status")["state"] == "executing"
        # An already dispatched action cannot honestly be cancelled. Do not
        # allow a second operation or reset state while it is running.
        assert request("cancel")["state"] == "error"
        assert request("start")["state"] == "error"
        assert request("run", text="mute")["state"] == "error"
        assert request("status")["state"] == "executing"
        assert len(calls) == 1
        release.set()
        wait(c)
        assert request("status")["state"] == "idle"
    finally:
        release.set()
        server.stop_event.set()
        thread.join(4)
    assert not thread.is_alive()


def test_worker_factory_failure_cleans_audio(tmp_path):
    c, calls = controller(tmp_path)

    def broken():
        raise RuntimeError("provider unavailable")

    c.worker_factory = broken
    c.start()
    with pytest.raises(VoiceError):
        c.stop()
    assert c.status()["state"] == "error"
    assert not (tmp_path / "audio.wav").exists() and c.recorder is None
    c.worker_factory = lambda: None
    c.start()
    c.cancel()
    assert not calls
    c.close()


def test_async_action_failure_visible_and_recoverable(tmp_path):
    c, _ = controller(tmp_path)

    def broken(*args, **kwargs):
        raise VoiceError("Desktop action failed")

    c.router.execute = broken
    assert c.run("mute")["state"] == "executing"
    wait(c)
    assert c.status() == {"state": "error", "message": "Desktop action failed"}
    assert c.cancel()["state"] == "idle"
    c.close()
