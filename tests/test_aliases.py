"""Exact alias enrollment and no-execution recording regressions."""

import json
import time

import pytest

from omarchy_voice.aliases import read_aliases, remove_alias, set_alias, update_alias
from omarchy_voice.cli import main
from omarchy_voice.config import Config, load_config
from omarchy_voice.core import DesktopRegistry, Router, VoiceError, parse
from omarchy_voice.service import Controller, dispatch


@pytest.fixture
def apps(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "empty"))
    directory = tmp_path / "data" / "applications"
    directory.mkdir(parents=True)
    (directory / "spotify.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Spotify\nIcon=spotify-client\nExec=spotify\n"
    )
    return directory / "spotify.desktop"


def test_exact_spoken_alias_survives_reload(apps):
    config = load_config()
    assert set_alias("Open is putty high.", "Spotify", config) == ("is putty high", "spotify.desktop")
    assert set_alias("music app", "Spotify", config) == ("music app", "spotify.desktop")
    assert read_aliases() == {"is putty high": "spotify.desktop", "music app": "spotify.desktop"}
    reloaded = load_config()
    for command in ("open is putty high", "open music app"):
        assert Router(reloaded).plan(parse(command)) == ["gio", "launch", str(apps)]
    with pytest.raises(VoiceError, match="not permitted"):
        Router(Config(aliases=reloaded.aliases, permissions=())).plan(parse("open music app"))
    remove_alias("music app")
    with pytest.raises(VoiceError, match="unavailable or ambiguous"):
        Router(load_config()).plan(parse("open music app"))


def test_alias_validation_and_file_safety(apps, tmp_path):
    config = load_config()
    for phrase in ("open music app; mute", "open music app && mute", "open ../spotify"):
        with pytest.raises(VoiceError):
            set_alias(phrase, "Spotify", config)
    with pytest.raises(VoiceError, match="unavailable or ambiguous"):
        set_alias("music app", "Spotify then mute", config)
    path = tmp_path / "config" / "omarchy-voice" / "aliases.json"
    path.symlink_to(tmp_path / "target")
    with pytest.raises(VoiceError, match="Unsafe alias file"):
        set_alias("music app", "Spotify", config)
    path.unlink()
    path.write_text('{"music app": "spotify.desktop"}')
    path.chmod(0o666)
    with pytest.raises(VoiceError, match="Unsafe alias file"):
        read_aliases()


def test_alias_cli_json_and_no_execution(apps, capsys):
    assert main(["apps"]) == 0
    listed = json.loads(capsys.readouterr().out)["apps"]
    assert any(app["id"] == "spotify.desktop" and app["name"] == "Spotify" and app.get("icon") for app in listed)
    assert "open spotify" in listed[0]["commands"]
    assert main(["alias", "set", "open music app", "Spotify"]) == 0
    assert json.loads(capsys.readouterr().out)["desktop_id"] == "spotify.desktop"
    assert main(["apps"]) == 0
    listed = json.loads(capsys.readouterr().out)["apps"]
    assert "open music app" in listed[0]["commands"]
    assert main(["alias", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["aliases"] == {"music app": "spotify.desktop"}
    assert main(["run", "open music app"]) == 0
    assert json.loads(capsys.readouterr().out)["argv"] == ["gio", "launch", str(apps)]
    assert main(["alias", "remove", "music app"]) == 0
    assert json.loads(capsys.readouterr().out)["phrase"] == "music app"


def test_update_alias_replaces_phrase_atomically(apps, capsys):
    config = load_config()
    set_alias("open music app", "Spotify", config)
    set_alias("open spotify", "Spotify", config)
    assert main(["alias", "update", "music app", "open favorite music", "spotify.desktop"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["phrase"] == "favorite music"
    assert read_aliases() == {"favorite music": "spotify.desktop", "spotify": "spotify.desktop"}
    assert Router(load_config()).plan(parse("open favorite music")) == ["gio", "launch", str(apps)]
    with pytest.raises(VoiceError, match="unavailable or ambiguous"):
        Router(load_config()).plan(parse("open music app"))
    for old, new in (("favorite music", "spotify"), ("missing", "another"),
                     ("favorite music", "open music app; mute")):
        with pytest.raises(VoiceError):
            update_alias(old, new, "spotify.desktop", load_config())
        assert read_aliases() == {"favorite music": "spotify.desktop", "spotify": "spotify.desktop"}


def test_taken_phrase_cannot_move_another_apps_commands(apps, capsys):
    applications = apps.parent
    (applications / "brave-browser.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Brave\nExec=brave\n"
    )
    (applications / "chromium.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Chromium\nExec=chromium\n"
    )
    config = load_config()
    brave = applications / "brave-browser.desktop"
    chromium = applications / "chromium.desktop"
    assert Router(config).plan(parse("open brave")) == ["gio", "launch", str(brave)]
    assert Router(config).plan(parse("open chromium")) == ["gio", "launch", str(chromium)]
    assert Router(config).plan(parse("open browser")) == ["omarchy", "launch", "browser"]
    for phrase in ("open chromium", "chromium", "open brave", "open brave browser"):
        with pytest.raises(VoiceError, match="already taken"):
            set_alias(phrase, "spotify.desktop", config)
        assert read_aliases() == {}
    assert set_alias("open browser", "chromium.desktop", config) == ("browser", "chromium.desktop")
    pinned = load_config()
    assert Router(pinned).plan(parse("open browser")) == ["gio", "launch", str(chromium)]
    assert Router(pinned).plan(parse("open brave")) == ["gio", "launch", str(brave)]
    assert Router(pinned).plan(parse("open chromium")) == ["gio", "launch", str(chromium)]
    assert main(["alias", "set", "open chromium", "brave-browser.desktop"]) == 1
    assert "already taken" in json.loads(capsys.readouterr().out)["message"]
    assert read_aliases() == {"browser": "chromium.desktop"}


def test_update_alias_keeps_old_phrase_when_target_is_invalid(apps):
    set_alias("music app", "Spotify", load_config())
    with pytest.raises(VoiceError):
        update_alias("music app", "new music", "missing.desktop", load_config())
    assert read_aliases() == {"music app": "spotify.desktop"}

def test_app_command_catalog_only_lists_valid_routes(apps, capsys, monkeypatch):
    (apps.parent / "brave-browser.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Brave\nExec=brave\n"
    )
    (apps.parent / "chromium.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Chromium\nExec=chromium\n"
    )
    (apps.parent / "plain.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Plain\nExec=plain\n"
    )
    monkeypatch.setattr("omarchy_voice.cli.default_browser_desktop_id", lambda: "brave-browser.desktop")
    assert main(["apps"]) == 0
    listed = {app["id"]: app["commands"] for app in json.loads(capsys.readouterr().out)["apps"]}
    assert "open browser" in listed["brave-browser.desktop"]
    assert "open brave" in listed["brave-browser.desktop"]
    assert "open chromium" in listed["chromium.desktop"]
    assert "open chromium" not in listed["brave-browser.desktop"]
    assert "open spotify" in listed["spotify.desktop"]
    assert "open a spotify" not in listed["spotify.desktop"]
    assert "open and spotify" not in listed["spotify.desktop"]
    assert "open is spotify" not in listed["spotify.desktop"]
    assert listed["plain.desktop"] == []
    assert len(listed["brave-browser.desktop"]) == len(set(listed["brave-browser.desktop"]))

    from omarchy_voice.cli import app_catalog
    denied = {app["id"]: app["commands"] for app in app_catalog(Config(permissions=()))}
    assert not any(denied.values())
    # An explicit saved browser phrase overrides only that role.
    conflicted = {app["id"]: app["commands"] for app in app_catalog(
        Config(aliases={"brave": "brave-browser.desktop", "spotify": "spotify.desktop",
                        "browser": "spotify.desktop"}),
        default_browser="brave-browser.desktop",
    )}
    assert "open browser" in conflicted["spotify.desktop"]
    assert "open browser" not in conflicted["brave-browser.desktop"]
    assert "open brave" in conflicted["brave-browser.desktop"]


def test_app_picker_excludes_hidden_and_untrusted_entries(apps, tmp_path, monkeypatch):
    applications = apps.parent
    (applications / "hidden.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Hidden\nExec=hidden\nNoDisplay=true\n"
    )
    unsafe = applications / "unsafe.desktop"
    unsafe.write_text("[Desktop Entry]\nType=Application\nName=Unsafe\nExec=unsafe\n")
    unsafe.chmod(0o666)
    result = DesktopRegistry([applications]).applications()
    assert result[0]["id"] == "spotify.desktop"
    assert result[0]["name"] == "Spotify"
    assert result[0]["icon"] in ("spotify-client",) or result[0]["icon"].endswith("spotify-client.png")
    (applications / "plain.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Plain\nExec=plain\n"
    )
    (applications / "path.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Path\nIcon=/usr/share/pixmaps/path.png\nExec=path\n"
    )
    (applications / "badicon.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Bad\nIcon=file:///tmp/x.png\nExec=bad\n"
    )
    icons = tmp_path / "icons" / "hicolor" / "48x48" / "apps"
    icons.mkdir(parents=True)
    (icons / "spotify-client.png").write_bytes(b"")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "empty"))
    listed = {app["id"]: app for app in DesktopRegistry([applications]).applications()}
    assert listed["plain.desktop"]["icon"] == ""
    assert listed["path.desktop"]["icon"] == "/usr/share/pixmaps/path.png"
    assert listed["badicon.desktop"]["icon"] == ""
    assert listed["spotify.desktop"]["icon"] == str(icons / "spotify-client.png")


def test_alias_recording_never_executes(tmp_path):
    audio = tmp_path / "recording.wav"
    actions = []

    class Recorder:
        def start(self):
            audio.write_bytes(b"fixture")

        def stop(self):
            return audio

        def cleanup(self):
            audio.unlink(missing_ok=True)

    class Worker:
        def transcribe(self, *_):
            return "Open is putty high."

        def cancel(self):
            pass

    config = Config()
    controller = Controller(
        config, recorder_factory=Recorder, worker_factory=Worker,
        router=Router(config, runner=lambda *a, **k: actions.append(a)),
    )
    try:
        assert dispatch(controller, {"command": "start_alias"})["state"] == "listening"
        dispatch(controller, {"command": "stop"})
        for _ in range(100):
            if controller.status()["state"] != "transcribing":
                break
            time.sleep(0.01)
        assert controller.status() == {
            "state": "alias_review", "message": "Review the heard phrase; no action was run",
            "alias_text": "Open is putty high.",
        }
        assert not actions and not audio.exists()
        controller.cancel()
        assert "alias_text" not in controller.status()
    finally:
        controller.close()


def test_alias_ipc_parameters_rejected(tmp_path):
    controller = Controller(Config())
    with pytest.raises(VoiceError, match="Unknown command"):
        dispatch(controller, {"command": "start_alias", "application": "spotify"})
    controller.close()


def test_keybind_osd_defaults_on_and_toggles(apps, tmp_path):
    from omarchy_voice.aliases import read_settings, set_keybind_osd

    assert read_settings() == {"keybind_osd": True}
    assert set_keybind_osd(False) is False
    assert read_settings() == {"keybind_osd": False}
    assert set_keybind_osd(True) is True
    path = tmp_path / "config" / "omarchy-voice" / "settings.json"
    assert path.stat().st_mode & 0o777 == 0o600


def test_stt_settings_cli_writes_config(apps, tmp_path, capsys):
    assert main(["settings", "show"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["stt"]["provider"] == "faster-whisper"
    assert shown["stt"]["model"] == "tiny.en"
    assert [row["value"] for row in shown["stt_options"]["providers"]] == ["faster-whisper"]
    assert main(["settings", "stt", "model", "base.en"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["stt"]["model"] == "base.en"
    assert "restart voice service" in saved["message"]
    config_path = tmp_path / "config" / "omarchy-voice" / "config.toml"
    assert 'model = "base.en"' in config_path.read_text()
    assert main(["settings", "stt", "provider", "whisper.cpp"]) == 1
    assert "Unsupported STT provider" in capsys.readouterr().out
