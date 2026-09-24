"""OSD copy and live Super+K chord lookup."""

import json
from types import SimpleNamespace

from omarchy_voice.core import Intent
from omarchy_voice.feedback import (
    OSD_DURATION_MS,
    OSD_ICON,
    load_keybinds,
    osd_message,
    parse_keybind_print,
    reset_keybinds,
    show_osd,
)

SAMPLE = """\
SUPER + RETURN                      → Terminal
SUPER SHIFT + RETURN                → Browser
SUPER SHIFT + F                     → File manager
SUPER + W                           → Close window
SUPER CTRL + L                      → Lock system
SUPER SHIFT ALT + B                 → Browser (private)
SUPER SHIFT + B                     → Browser
SUPER SHIFT + M                     → Music
SUPER + 4                           → Switch to workspace 4
SUPER SHIFT + 4                     → Move window to workspace 4
XF86AudioMute                       → Mute
XF86AudioRaiseVolume                → Volume up
XF86AudioLowerVolume                → Volume down
"""


def test_parse_keeps_first_chord_and_strips_private_suffix():
    table = parse_keybind_print(SAMPLE)
    assert table["Terminal"] == "SUPER + RETURN"
    assert table["Browser"] == "SUPER SHIFT + RETURN"
    assert "Browser (private)" not in table
    assert table["Mute"] == "XF86AudioMute"


def test_osd_shows_chord_only():
    reset_keybinds()
    runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=SAMPLE)
    assert osd_message(Intent("app.launch", {"application": "terminal"}), runner=runner) == (
        "SUPER + RETURN"
    )
    assert osd_message(Intent("app.launch", {"application": "brave"}), runner=runner) == (
        "SUPER SHIFT + RETURN"
    )
    assert osd_message(Intent("window.close", {}), runner=runner) == "SUPER + W"
    assert osd_message(Intent("audio.mute", {}), runner=runner) == "XF86AudioMute"
    assert osd_message(Intent("workspace.switch", {"number": 4}), runner=runner) == "SUPER + 4"
    assert osd_message(Intent("window.move_workspace", {"number": 4}), runner=runner) == (
        "SUPER SHIFT + 4"
    )
    assert osd_message(Intent("window.move_workspace", {"direction": "left"}), runner=runner) == ""


def test_osd_without_chord_is_silent():
    reset_keybinds()
    runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout="")
    assert osd_message(Intent("app.launch", {"application": "blender"}), runner=runner) == ""
    assert osd_message(Intent("workspace.switch", {"number": 3}), runner=runner) == ""


def test_osd_disabled_is_silent():
    reset_keybinds()
    runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=SAMPLE)
    assert osd_message(
        Intent("app.launch", {"application": "terminal"}), runner=runner, enabled=False
    ) == ""
    show_osd(Intent("app.launch", {"application": "terminal"}), runner=runner, enabled=False)


def test_load_keybinds_caches_then_refreshes():
    reset_keybinds()
    calls = []

    def runner(*a, **k):
        calls.append(1)
        return SimpleNamespace(returncode=0, stdout=SAMPLE)

    first = load_keybinds(runner=runner, now=10.0)
    second = load_keybinds(runner=runner, now=20.0)
    third = load_keybinds(runner=runner, now=50.0)
    assert first["Terminal"] == "SUPER + RETURN"
    assert second is first
    assert len(calls) == 2
    assert third["Terminal"] == "SUPER + RETURN"


def test_show_osd_payload_matches_launch_osd():
    reset_keybinds()
    calls = []

    def runner(argv, **kwargs):
        if argv[:4] == ["omarchy", "menu", "keybindings", "--print"]:
            return SimpleNamespace(returncode=0, stdout=SAMPLE)
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="")

    show_osd(Intent("app.launch", {"application": "terminal"}), runner=runner)
    argv, kwargs = calls[0]
    assert argv[:3] == ["omarchy-shell", "osd", "show"]
    payload = json.loads(argv[3])
    assert payload == {
        "icon": OSD_ICON,
        "message": "SUPER + RETURN",
        "duration": OSD_DURATION_MS,
    }
    assert kwargs["check"] is False


def test_show_osd_skips_when_no_chord():
    reset_keybinds()
    calls = []

    def runner(argv, **kwargs):
        if argv[:4] == ["omarchy", "menu", "keybindings", "--print"]:
            return SimpleNamespace(returncode=0, stdout="")
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="")

    show_osd(Intent("app.launch", {"application": "blender"}), runner=runner)
    assert calls == []
