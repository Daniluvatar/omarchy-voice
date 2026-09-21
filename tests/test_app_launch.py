"""Launch lifecycle regressions using only harmless Python child processes."""
import os
import subprocess
import sys
import time

import pytest

from omarchy_voice import core
from omarchy_voice.config import Config
from omarchy_voice.core import DesktopRegistry, Intent, Router, VoiceError, parse


@pytest.mark.parametrize("text", ["open the terminal", "Open the terminal.", "launch the terminal", "start the terminal"])
def test_terminal_article(text):
    router = Router(Config())
    assert parse(text) == Intent("app.launch", {"application": "terminal"})
    assert router.plan(parse(text)) == ["omarchy", "launch", "terminal"]


@pytest.mark.parametrize("text", ["open the brave", "open the terminal then mute", "open the terminal please"])
def test_article_is_not_generally_stripped(text):
    intent = parse(text)
    assert intent.parameters["application"] == text.removeprefix("open ")
    with pytest.raises(VoiceError):
        Router(Config(), registry=DesktopRegistry([])).plan(intent)


@pytest.mark.parametrize("text", ["open the terminal; mute", "open the terminal && mute", "open the terminal $(id)"])
def test_terminal_injection_rejected(text):
    with pytest.raises(VoiceError):
        parse(text)


@pytest.fixture
def children(monkeypatch):
    """Intercept only executable selection; keep real Popen and wait behavior."""
    original = subprocess.Popen
    spawned = []
    calls = []

    def install(code):
        def popen(argv, **kwargs):
            calls.append((argv, kwargs))
            process = original([sys.executable, "-c", code], **kwargs)
            spawned.append(process)
            return process
        monkeypatch.setattr(core.subprocess, "Popen", popen)
        return spawned, calls

    yield install
    for process in spawned:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def eventually(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "child did not reach expected state"
        time.sleep(0.01)


def test_app_survives_old_timeout_and_is_reaped(children, tmp_path):
    marker = tmp_path / "survived"
    processes, calls = children(
        "import pathlib, time; time.sleep(10.5); "
        f"pathlib.Path({str(marker)!r}).write_text('alive'); time.sleep(0.2)"
    )
    start = time.monotonic()
    Router(Config()).execute(parse("open the terminal"))
    assert time.monotonic() - start < 3
    process = processes[0]
    assert process.returncode is None
    assert os.getsid(process.pid) == process.pid
    assert calls == [(["omarchy", "launch", "terminal"], {
        "shell": False, "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
        "close_fds": True, "start_new_session": True,
    })]
    eventually(lambda: marker.exists(), seconds=15)
    assert marker.read_text() == "alive"
    # Do not poll/wait here: the production reaper must collect it unaided.
    eventually(lambda: process.returncode == 0)
    with pytest.raises(ChildProcessError):
        os.waitpid(process.pid, os.WNOHANG)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_early_exit_detected_and_reaped(children, exit_code):
    processes, _ = children(f"raise SystemExit({exit_code})")
    router = Router(Config())
    if exit_code:
        with pytest.raises(VoiceError, match="Desktop action failed"):
            router.execute(parse("open terminal"))
    else:
        router.execute(parse("open terminal"))
    assert processes[0].returncode == exit_code
    with pytest.raises(ChildProcessError):
        os.waitpid(processes[0].pid, os.WNOHANG)


def test_reaper_start_failure_does_not_spawn(monkeypatch):
    def exhausted(*args):
        raise RuntimeError("cannot start new thread")
    monkeypatch.setattr(core.threading.Thread, "start", exhausted)
    monkeypatch.setattr(core.subprocess, "Popen", lambda *a, **k: pytest.fail("spawned without reaper"))
    with pytest.raises(VoiceError, match="Desktop action failed"):
        Router(Config()).execute(parse("open terminal"))


def test_missing_launcher(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("fixture")
    monkeypatch.setattr(core.subprocess, "Popen", missing)
    with pytest.raises(VoiceError, match="Desktop action failed"):
        Router(Config()).execute(parse("open terminal"))


@pytest.mark.parametrize("replace", [False, True])
def test_injected_runner_never_bypassed(monkeypatch, replace):
    monkeypatch.setattr(core.subprocess, "Popen", lambda *a, **k: pytest.fail("real launch"))
    calls = []
    runner = lambda *a, **k: calls.append((a, k))
    router = Router(Config()) if replace else Router(Config(), runner=runner)
    if replace:
        router.runner = runner
    router.execute(parse("open terminal"))
    assert calls[0][0] == (["omarchy", "launch", "terminal"],)
    assert calls[0][1]["timeout"] == 10


def test_other_actions_remain_bounded():
    calls = []
    Router(Config(), runner=lambda *a, **k: calls.append((a, k))).execute(parse("mute"))
    assert calls[0][0][0][0] == "wpctl"
    assert calls[0][1]["timeout"] == 10


def test_denied_launch_never_spawns(monkeypatch):
    monkeypatch.setattr(core.subprocess, "Popen", lambda *a, **k: pytest.fail("real launch"))
    with pytest.raises(VoiceError, match="not permitted"):
        Router(Config(permissions=())).execute(parse("open the terminal"))


def test_terminal_alias_uses_same_launch_path(children, tmp_path):
    desktop = tmp_path / "foot.desktop"
    desktop.write_text("[Desktop Entry]\nType=Application\nName=Foot\nExec=foot\n")
    config = Config(aliases={"terminal": "foot.desktop"})
    processes, calls = children("pass")
    Router(config, registry=DesktopRegistry([tmp_path], config.aliases)).execute(parse("open the terminal"))
    assert calls[0][0] == ["gio", "launch", str(desktop)]
    assert processes[0].returncode == 0
