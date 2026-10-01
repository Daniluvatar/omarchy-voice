#!/usr/bin/env python3
"""Assert the real panel reorders after asynchronous source updates.

A fixture that supplies both catalogs before the first binding evaluation does
not reproduce the live failure. This harness instantiates VoicePanel.qml, lets
its own startup refresh finish against an empty CLI, then assigns one source
and the other later. pagedApps must change on its own in both orders, and when
the last routable command is added or removed, without recreating the panel.
"""
import os
from pathlib import Path
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
SHELL = Path('/usr/share/omarchy/shell')

MOCK_CLI = '''#!/usr/bin/env python3
import json
import sys
args = sys.argv[1:]
if args == ['apps']:
    print(json.dumps({"state": "idle", "message": "fixture", "apps": [], "voice_commands_revision": "async"}))
elif args[:2] == ['voice-command', 'list']:
    print(json.dumps({"state": "idle", "message": "fixture", "voice_commands": {}}))
elif args[:2] == ['settings', 'show']:
    print(json.dumps({"state": "idle", "message": "fixture"}))
else:
    print(json.dumps({"state": "idle", "message": "fixture"}))
'''

HARNESS = r'''import QtQuick
import Quickshell
import "Plugin"
ShellRoot {
    property var panel: null
    property string stage: "boot"
    property int ticks: 0
    property string beforeCommands: ""
    property string beforeCatalog: ""
    property string beforeRemove: ""

    function fail(message) { console.error("FAIL async order: " + message); Qt.quit() }
    function ids(list) {
        var out = []
        for (var i = 0; i < list.length; i++) out.push(list[i].id)
        return out.join(",")
    }
    function catalog() {
        return [
            { id: "aether.desktop", name: "Aether", icon: "", commands: [] },
            { id: "brave-browser.desktop", name: "Brave", icon: "", commands: ["open brave"] },
            { id: "spotify.desktop", name: "Spotify", icon: "", commands: [] }
        ]
    }
    function savedSpotify() {
        return [{ phrase: "music app", desktopId: "spotify.desktop", appLabel: "Spotify" }]
    }
    Component.onCompleted: {
        var component = Qt.createComponent("Plugin/VoicePanel.qml")
        if (component.status !== Component.Ready) { fail("panel compile: " + component.errorString()); return }
        panel = component.createObject(null)
        if (!panel) { fail("panel creation failed"); return }
        panel.open()
    }
    Timer {
        interval: 50
        repeat: true
        running: panel !== null
        onTriggered: {
            ticks++
            if (stage === "boot") {
                if (!panel.appsLoaded || !panel.commandsLoaded) {
                    if (ticks > 80) fail("startup refresh did not settle")
                    return
                }
                // Catalog is already loaded. Saved commands are still empty.
                panel.appCatalog = catalog()
                panel.commandEntries = []
                stage = "catalog-first"
                ticks = 0
                return
            }
            if (stage === "catalog-first") {
                if (ticks < 2) return
                beforeCommands = ids(panel.pagedApps)
                if (beforeCommands !== "brave-browser.desktop,aether.desktop,spotify.desktop")
                    fail("catalog-first baseline got=" + beforeCommands)
                panel.commandEntries = savedSpotify()
                stage = "commands-later"
                ticks = 0
                return
            }
            if (stage === "commands-later") {
                if (ticks < 2) return
                var after = ids(panel.pagedApps)
                if (after === beforeCommands)
                    fail("pagedApps did not change after commandEntries arrived; still=" + after)
                if (after !== "brave-browser.desktop,spotify.desktop,aether.desktop")
                    fail("commands-later got=" + after)
                var shown = panel.visibleApplicationIds().join(",")
                if (shown !== after)
                    fail("repeater did not follow pagedApps; shown=" + shown + " model=" + after)
                // Opposite order on the same instance: drop both sources, then
                // deliver commands before the catalog.
                panel.appCatalog = []
                panel.commandEntries = []
                stage = "cleared"
                ticks = 0
                return
            }
            if (stage === "cleared") {
                if (ticks < 2) return
                panel.commandEntries = savedSpotify()
                stage = "commands-first"
                ticks = 0
                return
            }
            if (stage === "commands-first") {
                if (ticks < 2) return
                beforeCatalog = ids(panel.pagedApps)
                panel.appCatalog = catalog()
                stage = "catalog-later"
                ticks = 0
                return
            }
            if (stage === "catalog-later") {
                if (ticks < 2) return
                var joined = ids(panel.pagedApps)
                if (joined === beforeCatalog)
                    fail("pagedApps did not change after appCatalog arrived; still=" + joined)
                if (joined !== "brave-browser.desktop,spotify.desktop,aether.desktop")
                    fail("catalog-later got=" + joined)
                panel.commandEntries = []
                stage = "removed"
                ticks = 0
                return
            }
            if (stage === "removed") {
                if (ticks < 2) return
                var sunk = ids(panel.pagedApps)
                if (sunk !== "brave-browser.desktop,aether.desktop,spotify.desktop")
                    fail("remove last saved command got=" + sunk)
                if (panel.visibleApplicationIds().join(",") !== sunk)
                    fail("repeater stayed configured after removal; shown=" + panel.visibleApplicationIds().join(","))
                panel.commandEntries = savedSpotify()
                stage = "added"
                ticks = 0
                return
            }
            if (stage === "added") {
                if (ticks < 2) return
                var promoted = ids(panel.pagedApps)
                if (promoted !== "brave-browser.desktop,spotify.desktop,aether.desktop")
                    fail("add first saved command got=" + promoted)
                if (panel.visibleApplicationIds().join(",") !== promoted)
                    fail("repeater did not promote after add; shown=" + panel.visibleApplicationIds().join(","))
                console.log("PASS async order: both source orders and add/remove reordered pagedApps")
                panel.destroy()
                Qt.quit()
            }
        }
    }
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='voice-panel-async-', dir=os.environ.get('TMPDIR')) as temp:
        root = Path(temp)
        for name in ('Commons', 'Ui', 'services'):
            (root / name).symlink_to(SHELL / name, target_is_directory=True)
        (root / 'Plugin').symlink_to(REPO / 'plugin', target_is_directory=True)
        (root / 'shell.qml').write_text(HARNESS)
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        mock = bin_dir / 'omarchy-voice'
        mock.write_text(MOCK_CLI)
        mock.chmod(0o700)
        env = dict(os.environ, QT_QPA_PLATFORM='wayland',
                   PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
        proc = subprocess.Popen(['quickshell', '--no-color', '-p', str(root)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            print(out, end='')
            raise SystemExit('Async panel ordering validation timed out')
        print(out, end='')
        text = out or ''
        if (proc.returncode != 0 or 'FAIL async order' in text or
                'PASS async order' not in text or
                'ReferenceError:' in text or 'TypeError:' in text):
            raise SystemExit('Async panel ordering validation failed')


if __name__ == '__main__':
    main()
