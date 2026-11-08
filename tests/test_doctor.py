"""Doctor readiness checks: honest capability reporting, not live actions."""

import json

import pytest

from omarchy_voice.cli import doctor_report, main
from omarchy_voice.config import Config
from omarchy_voice.core import VoiceError


ALL_PROGRAMS = {"pw-record", "hyprctl", "wpctl", "gio", "omarchy", "systemd-run", "xdg-settings", "xdg-mime"}


def arrange(monkeypatch, tmp_path, *, programs=ALL_PROGRAMS, model=True, av=True, runtime=True, scope=True):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name in programs else None)
    monkeypatch.setattr("omarchy_voice.cli.FasterWhisper.available", lambda self: True)
    monkeypatch.setattr("omarchy_voice.cli.cached_model", lambda config: model)
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda name: object() if av and name == "av" else None
    )
    if runtime:
        monkeypatch.setattr("omarchy_voice.cli.runtime_dir", lambda: tmp_path)
    else:
        def unavailable():
            raise VoiceError("runtime unavailable")

        monkeypatch.setattr("omarchy_voice.cli.runtime_dir", unavailable)
    monkeypatch.setattr("omarchy_voice.cli.user_scope_ready", lambda: scope)


def test_doctor_passes_when_required_checks_are_present(monkeypatch, tmp_path):
    arrange(monkeypatch, tmp_path)
    result = doctor_report(Config())
    assert result["state"] == "idle"
    assert result["missing"] == []
    assert result["warnings"] == []
    assert result["checks"]["model_available"] is True
    assert result["checks"]["user_scope_ready"] is True


def test_doctor_reports_missing_required_program(monkeypatch, tmp_path):
    arrange(monkeypatch, tmp_path, programs=ALL_PROGRAMS - {"pw-record", "gio"})
    result = doctor_report(Config())
    assert result["state"] == "error"
    assert "pw-record" in result["missing"]
    assert "gio" in result["missing"]


def test_doctor_reports_missing_stt_and_av_dependencies(monkeypatch, tmp_path):
    arrange(monkeypatch, tmp_path, av=False, scope=True)
    monkeypatch.setattr("omarchy_voice.cli.FasterWhisper.available", lambda self: False)
    result = doctor_report(Config())
    assert result["state"] == "error"
    assert "stt_dependency" in result["missing"]
    assert "av_dependency" in result["missing"]


def test_doctor_reports_missing_systemd_run(monkeypatch, tmp_path):
    arrange(monkeypatch, tmp_path, programs=ALL_PROGRAMS - {"systemd-run"}, scope=False)
    result = doctor_report(Config())
    assert result["state"] == "error"
    assert "systemd-run" in result["missing"]
    assert "user_scope_ready" in result["missing"]


def test_doctor_reports_runtime_and_user_scope_failures(monkeypatch, tmp_path):
    arrange(monkeypatch, tmp_path, runtime=False, scope=False)
    result = doctor_report(Config())
    assert result["state"] == "error"
    assert "runtime_directory" in result["missing"]
    assert "user_scope_ready" in result["missing"]


def test_doctor_treats_model_and_browser_tools_as_warnings(monkeypatch, tmp_path):
    arrange(monkeypatch, tmp_path, programs=ALL_PROGRAMS - {"xdg-settings", "xdg-mime"}, model=False)
    result = doctor_report(Config())
    assert result["state"] == "idle"
    assert result["missing"] == []
    assert any("download-model" in warning for warning in result["warnings"])
    assert any("xdg-settings" in warning for warning in result["warnings"])
    assert any("xdg-mime" in warning for warning in result["warnings"])


def test_doctor_cli_returns_json_and_error_exit_code(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    arrange(monkeypatch, tmp_path, programs=ALL_PROGRAMS - {"hyprctl"})
    assert main(["doctor"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "error"
    assert "hyprctl" in data["missing"]
