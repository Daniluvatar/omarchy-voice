import time
import pytest
from omarchy_voice.core import Intent, parse, Router, DesktopRegistry, VoiceError
from omarchy_voice.config import Config, load_config
from omarchy_voice.service import Controller, runtime_dir


@pytest.mark.parametrize(
    "text,action,params",
    [
        ("Open Brave", "app.launch", {"application": "brave"}),
        ("Open, brave.", "app.launch", {"application": "brave"}),
        ("open brave browser", "app.launch", {"application": "brave"}),
        ("open browser", "app.launch", {"application": "brave"}),
        ("open chromium", "app.launch", {"application": "brave"}),
        ("launch terminal", "app.launch", {"application": "terminal"}),
        ("Open terminal. Open terminal.", "app.launch", {"application": "terminal"}),
        ("open term", "app.launch", {"application": "terminal"}),
        ("open termina", "app.launch", {"application": "terminal"}),
        ("open terminator", "app.launch", {"application": "terminal"}),
        ("open ghostty", "app.launch", {"application": "terminal"}),
        ("start Spotify", "app.launch", {"application": "spotify"}),
        ("close window", "window.close", {}),
        ("workspace ten", "workspace.switch", {"number": 10}),
        ("workspace 1", "workspace.switch", {"number": 1}),
        ("volume up", "audio.volume", {"direction": "up"}),
        ("volume down", "audio.volume", {"direction": "down"}),
        ("mute", "audio.mute", {}),
        ("lock computer", "system.lock", {}),
        ("move window left", "window.move_monitor", {"direction": "left"}),
        ("move this left", "window.move_monitor", {"direction": "left"}),
        ("move this window to the left", "window.move_monitor", {"direction": "left"}),
        ("move this window to the left screen", "window.move_monitor", {"direction": "left"}),
        ("move the window to the left", "window.move_monitor", {"direction": "left"}),
        ("move it to the left", "window.move_monitor", {"direction": "left"}),
        ("move window right", "window.move_monitor", {"direction": "right"}),
        ("move this right", "window.move_monitor", {"direction": "right"}),
        ("move this window to the right", "window.move_monitor", {"direction": "right"}),
        ("move window to other screen", "window.move_monitor", {"direction": "other"}),
        ("move this to other screen", "window.move_monitor", {"direction": "other"}),
        ("move this window to the other monitor", "window.move_monitor", {"direction": "other"}),
        ("switch to workspace four", "window.move_workspace", {"number": 4}),
        ("switch to work space 4", "window.move_workspace", {"number": 4}),
        ("Switch to water space forward.", "window.move_workspace", {"number": 4}),
        ("Switch to World Space 1.", "window.move_workspace", {"number": 1}),
        ("switch in this window to water space for", "window.move_workspace", {"number": 4}),
        ("move this window to workspace 4", "window.move_workspace", {"number": 4}),
        ("move window to the left workspace", "window.move_workspace", {"direction": "left"}),
        ("switch to the next workspace", "window.move_workspace", {"direction": "right"}),
        ("move this to previous workspace", "window.move_workspace", {"direction": "left"}),
        ("Move these to the right.", "window.move_monitor", {"direction": "right"}),
        ("Move window to the rest.", "window.move_monitor", {"direction": "right"}),
        ("No, this window to the right.", "window.move_monitor", {"direction": "right"}),
    ],
)
def test_parse(text, action, params):
    assert parse(text) == Intent(action, params)


@pytest.mark.parametrize(
    "text",
    [
        "open brave; reboot",
        "open brave && mute",
        "workspace 11",
        "workspace 0",
        "please mute",
        "shutdown",
        "confirm token",
        "mute then lock computer",
        "close spotify",
        "open ../../bin/sh",
        "move window one left",
        "move window 1 to left screen",
        "move brave left",
        "switch to workspace 11",
        "move window to workspace zero",
        "to the left is clean",
    ],
)
def test_reject(text):
    with pytest.raises(VoiceError):
        parse(text)


def test_router_strict():
    router = Router(Config(), runner=lambda *a, **k: pytest.fail("executed"))
    for intent in [
        Intent("shell", {}),
        Intent("workspace.switch", {"number": True}),
        Intent("audio.mute", {"extra": 1}),
        Intent("workspace.switch", {"number": "1"}),
    ]:
        with pytest.raises(VoiceError):
            router.plan(intent)
    with pytest.raises(VoiceError):
        router.execute(Intent("window.close", {}))
    assert router.plan(parse("volume up")) == [
        "wpctl",
        "set-volume",
        "-l",
        "1.0",
        "@DEFAULT_AUDIO_SINK@",
        "5%+",
    ]


def test_open_terminal_uses_omarchy_default():
    router = Router(Config(), runner=lambda *a, **k: pytest.fail("executed"))
    assert router.plan(parse("open terminal")) == ["omarchy", "launch", "terminal"]
    aliased = Router(
        Config(aliases={"terminal": "foot.desktop"}),
        registry=DesktopRegistry([], {"terminal": "foot.desktop"}),
        runner=lambda *a, **k: pytest.fail("executed"),
    )
    with pytest.raises(VoiceError):
        aliased.plan(parse("open terminal"))


def test_permissions():
    with pytest.raises(VoiceError):
        Router(Config(permissions=()), runner=lambda *a, **k: None).plan(parse("mute"))


def test_config(tmp_path):
    p = tmp_path / "config.toml"
    for text in [
        "unknown = true",
        '[stt]\nprovider="fake"',
        "[audio]\nmax_seconds=0",
        '[permissions]\nallow=["shell"]',
        "[stt]\nnetwork=true",
    ]:
        p.write_text(text)
        with pytest.raises(VoiceError):
            load_config(p)
    p.write_text('[stt]\nmodel="tiny.en"\n[audio]\nmax_seconds=4\n')
    assert load_config(p).max_seconds == 4


def test_desktop(tmp_path):
    p = tmp_path / "brave-browser.desktop"
    p.write_text("[Desktop Entry]\nType=Application\nName=Brave\nExec=brave %U\n")
    registry = DesktopRegistry([tmp_path], {"brave": "brave-browser.desktop"})
    assert registry.resolve("brave") == p
    with pytest.raises(VoiceError):
        registry.resolve("bra")
    p.write_text(
        "[Desktop Entry]\nType=Application\nName=Brave\nHidden=true\nExec=brave\n"
    )
    with pytest.raises(VoiceError):
        DesktopRegistry([tmp_path], {}).resolve("brave")


class Recorder:
    def __init__(self, path):
        self.path = path
        self.closed = False

    def start(self):
        self.path.write_bytes(b"audio")

    def stop(self):
        return self.path

    def cleanup(self):
        self.closed = True
        self.path.unlink(missing_ok=True)


class Worker:
    def __init__(self, text="mute"):
        self.text = text
        self.closed = False

    def transcribe(self, path, language, cancel):
        return self.text

    def cancel(self):
        self.closed = True


def controller(tmp_path, text="mute", **kwargs):
    calls = []

    def runner(argv, **kwargs):
        if argv == ["hyprctl", "-j", "activewindow"]:
            from types import SimpleNamespace
            return SimpleNamespace(stdout='{"address":"0x123abc"}')
        calls.append(argv)

    c = Controller(
        Config(**kwargs),
        recorder_factory=lambda: Recorder(tmp_path / "audio.wav"),
        worker_factory=lambda: Worker(text),
        router=Router(Config(), runner=runner),
    )
    return c, calls


def wait(c):
    for _ in range(100):
        if c.status()["state"] not in ("transcribing", "executing"):
            return
        time.sleep(0.01)
    pytest.fail("worker did not finish")


def test_lifecycle(tmp_path):
    c, calls = controller(tmp_path)
    assert c.start()["state"] == "listening"
    c.stop()
    wait(c)
    assert c.status()["state"] == "idle" and len(calls) == 1
    assert not (tmp_path / "audio.wav").exists()
    c.close()


def test_confirmation(tmp_path):
    c, calls = controller(tmp_path, "close window")
    c.start()
    c.stop()
    wait(c)
    s = c.status()
    assert s["state"] == "confirmation" and not calls
    with pytest.raises(VoiceError):
        c.confirm("wrong")
    assert c.confirm(s["confirmation_token"])["state"] == "executing"
    wait(c)
    assert len(calls) == 1
    with pytest.raises(VoiceError):
        c.confirm(s["confirmation_token"])
    c.close()


def test_cancel(tmp_path):
    c, calls = controller(tmp_path)
    c.start()
    c.cancel()
    assert (
        c.status()["state"] == "idle"
        and not calls
        and not (tmp_path / "audio.wav").exists()
    )
    c.close()


def test_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    p = runtime_dir()
    assert p.stat().st_mode & 0o777 == 0o700
    p.chmod(0o755)
    with pytest.raises(VoiceError):
        runtime_dir()
