import json
from pathlib import Path
import tomllib

import omarchy_voice


ROOT = Path(__file__).resolve().parents[1]


def test_root_manifest_is_the_install_manifest():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["schemaVersion"] == 1
    assert manifest["id"] == "local.omarchy-voice"
    assert manifest["kinds"] == ["bar-widget"]
    assert manifest["entryPoints"] == {"barWidget": "plugin/VoicePanel.qml"}

    entry = ROOT / manifest["entryPoints"]["barWidget"]
    assert entry.is_file()
    assert not entry.is_symlink()
    assert not (ROOT / "plugin" / "manifest.json").exists()


def test_plugin_assets_have_no_symlinks():
    plugin = ROOT / "plugin"
    assert plugin.is_dir()
    assert not plugin.is_symlink()
    for path in plugin.rglob("*"):
        assert not path.is_symlink(), f"plugin asset is a symlink: {path}"


def test_root_manifest_does_not_point_outside_the_repository():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    entry = (ROOT / manifest["entryPoints"]["barWidget"]).resolve()
    assert entry.is_relative_to(ROOT.resolve())


def test_manifest_and_package_versions_match():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert manifest["version"] == project["project"]["version"] == omarchy_voice.__version__
