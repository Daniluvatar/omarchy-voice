#!/usr/bin/env python3
"""Exercise the real panel's asynchronous refresh flow with a harmless CLI fixture.

The fixture is confined to TMPDIR and never touches the user's alias store,
voice service, microphone, or desktop actions. It does not replace live UI QA.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
SHELL = Path('/usr/share/omarchy/shell')

MOCK_CLI = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
import time

state_file = Path(os.environ['VOICE_PANEL_TEST_STATE'])
with open(os.environ['VOICE_PANEL_TEST_CALLS'], 'a') as calls:
    calls.write(json.dumps(sys.argv[1:]) + '\\n')
state = json.loads(state_file.read_text())
def save_state():
    next_file = state_file.with_suffix('.next')
    next_file.write_text(json.dumps(state))
    next_file.replace(state_file)
args = sys.argv[1:]
response = {'state': 'idle', 'message': 'fixture'}
code = 0
if args == ['providers']:
    response['providers'] = []
elif args == ['status']:
    response['message'] = 'Ready'
elif args == ['settings', 'show']:
    pass
elif args == ['apps']:
    response['apps'] = [
        {'id': ident, 'name': name, 'icon': '',
         'commands': ['open ' + phrase for phrase, target in state['aliases'].items() if target == ident]
                     + (['open beta alternate ' + str(i) for i in range(16)] if ident == 'beta.desktop' else [])}
        for ident, name in [('alpha.desktop', 'Alpha'), ('beta.desktop', 'Beta')]
    ]
elif args[:2] == ['alias', 'list']:
    response['aliases'] = state['aliases']
elif args[:2] == ['alias', 'set'] and args[2] == 'fail phrase':
    response = {'state': 'error', 'message': 'Simulated write failure'}
    code = 1
elif args[:2] == ['alias', 'set']:
    time.sleep(0.08)  # make the reopen/list request overlap the write
    state['aliases'][args[2].removeprefix('open ')] = args[3]
    save_state()
elif args[:2] == ['alias', 'update']:
    previous = args[2].removeprefix('open ')
    state['aliases'].pop(previous)
    state['aliases'][args[3].removeprefix('open ')] = args[4]
    save_state()
elif args[:2] == ['alias', 'remove']:
    state['aliases'].pop(args[2])
    save_state()
else:
    response = {'state': 'error', 'message': 'Unexpected fixture request'}
    code = 1
print(json.dumps(response))
raise SystemExit(code)
'''

HARNESS = '''import QtQuick
import Quickshell
import "Plugin"
ShellRoot {
    property var panel
    property int phase: 0
    property int ticks: 0
    property int reopenedAt: 0
    function fail(message) { console.error("FAIL panel refresh: " + message); Qt.quit() }
    function has(phrase) {
        for (var i = 0; i < panel.selectedAppCommands.length; i++)
            if (panel.selectedAppCommands[i].phrase === phrase) return true
        return false
    }
    Component.onCompleted: {
        var component = Qt.createComponent("Plugin/VoicePanel.qml")
        if (component.status !== Component.Ready) { fail(component.errorString()); return }
        panel = component.createObject(null)
        if (!panel) fail("panel instantiation failed: " + component.errorString())
    }
    Timer {
        interval: 30
        repeat: true
        running: true
        onTriggered: {
            ticks++
            if (ticks > 170) { fail("timed out in phase " + phase); return }
            if (phase === 0 && panel.appCatalog.length === 2 && panel.aliasEntries.length === 2) {
                panel.selectApp({id: "alpha.desktop"})
                if (!has("open first phrase") || has("open other phrase")) { fail("wrong app rows on initial selection"); return }
                panel.aliasRequest(["set", "new phrase", "alpha.desktop"])
                panel.refreshAliases() // queued while set is still running
                panel.selectApp({id: "beta.desktop"})
                if (!has("open other phrase") || has("open first phrase")) { fail("old app rows leaked after switch"); return }
                phase = 1
            } else if (phase === 1 && panel.aliasEntries.some(function(a) { return a.phrase === "new phrase" }) &&
                       panel.appCatalog.some(function(a) { return a.id === "alpha.desktop" && a.commands.indexOf("open new phrase") >= 0 })) {
                if (has("open new phrase")) { fail("new alias appeared under wrong app"); return }
                panel.selectApp({id: "alpha.desktop"})
                if (!has("open new phrase") || !panel.aliasesPendingApply) { fail("saved phrase not shown as pending"); return }
                panel.aliasRequest(["update", "new phrase", "renamed phrase", "alpha.desktop"])
                phase = 2
            } else if (phase === 2 && panel.aliasEntries.some(function(a) { return a.phrase === "renamed phrase" }) &&
                       panel.appCatalog.some(function(a) { return a.id === "alpha.desktop" && a.commands.indexOf("open renamed phrase") >= 0 })) {
                if (has("open new phrase") || !has("open renamed phrase")) { fail("rename did not refresh routed rows"); return }
                panel.aliasRequest(["remove", "renamed phrase"])
                phase = 3
            } else if (phase === 3 && !panel.aliasEntries.some(function(a) { return a.phrase === "renamed phrase" }) &&
                       !panel.appCatalog.some(function(a) { return a.id === "alpha.desktop" && a.commands.indexOf("open renamed phrase") >= 0 })) {
                if (has("open renamed phrase")) { fail("removed phrase still displayed"); return }
                panel.addingCommand = true
                panel.aliasRequest(["set", "fail phrase", "alpha.desktop"])
                phase = 4
            } else if (phase === 4 && panel.aliasStatus === "Simulated write failure") {
                if (!panel.addingCommand || has("open fail phrase") || !has("open first phrase")) {
                    fail("failed write discarded editor or changed rows"); return
                }
                panel.catalog = "desktop"
                if (panel.appChoice !== "" || panel.addingCommand || panel.selectedAppCommands.length !== 0) {
                    fail("Desktop navigation retained stale app details"); return
                }
                panel.catalog = "apps"
                panel.selectApp({id: "beta.desktop"})
                panel.open()
                panel.close()
                panel.open() // onOpenedChanged refreshes both lists again
                if (!panel.opened) { fail("panel failed to reopen"); return }
                panel.editSavedPhrase("other phrase", "open other phrase")
                if (panel.editingPhrase !== "other phrase" || !panel.addingCommand || panel.voiceInputMode !== "type") {
                    fail("edit pencil did not open the prefilled update form"); return
                }
                reopenedAt = ticks
                phase = 5
            } else if (phase === 5 && ticks >= reopenedAt + 12 && panel.editingPhrase === "other phrase" &&
                       has("open other phrase") && !has("open first phrase")) {
                if (!panel.commandEditorInView()) { fail("update editor was not scrolled into view after layout"); return }
                console.log("PASS panel refresh: queued save/list, switch, update, remove, failed write, Desktop, reopen and update editor")
                panel.close()
                panel.destroy()
                Qt.quit()
            }
        }
    }
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='voice-panel-refresh-', dir=os.environ.get('TMPDIR')) as temp:
        root = Path(temp)
        for name in ('Commons', 'Ui', 'services'):
            (root / name).symlink_to(SHELL / name, target_is_directory=True)
        (root / 'Plugin').symlink_to(REPO / 'plugin', target_is_directory=True)
        (root / 'shell.qml').write_text(HARNESS)
        state = root / 'state.json'
        state.write_text('{"aliases":{"first phrase":"alpha.desktop","other phrase":"beta.desktop"}}')
        calls = root / 'calls.jsonl'
        calls.touch()
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        mock_cli = bin_dir / 'omarchy-voice'
        mock_cli.write_text(MOCK_CLI)
        mock_cli.chmod(0o700)
        env = dict(os.environ, QT_QPA_PLATFORM='wayland', VOICE_PANEL_TEST_STATE=str(state), VOICE_PANEL_TEST_CALLS=str(calls),
                   PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
        result = subprocess.run(['quickshell', '--no-color', '-p', str(root)], env=env,
                                capture_output=True, text=True, timeout=20)
        print(result.stdout, end='')
        print(result.stderr, end='')
        if result.returncode or 'FAIL panel refresh' in result.stdout + result.stderr or 'PASS panel refresh' not in result.stdout + result.stderr or 'ReferenceError:' in result.stderr or 'TypeError:' in result.stderr:
            raise SystemExit('Panel refresh validation failed')
        requests = [json.loads(line) for line in calls.read_text().splitlines()]
        if requests.count(['alias', 'list']) < 5 or requests.count(['apps']) < 5:
            raise SystemExit(f'Panel did not refresh on every mutation and reopen: {requests}')


if __name__ == '__main__':
    main()
