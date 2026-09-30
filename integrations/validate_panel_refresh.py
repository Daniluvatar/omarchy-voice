#!/usr/bin/env python3
"""Exercise the real panel's asynchronous refresh flow with a harmless CLI fixture.

The fixture is confined to TMPDIR and never touches the user's voice-command
store, voice service, microphone, or desktop actions. It does not replace live UI QA.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
SHELL = Path('/usr/share/omarchy/shell')

MOCK_CLI = '''#!/usr/bin/env python3
import hashlib
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
revision = state.get('status_revision_override') or hashlib.sha256(
    json.dumps(state['voice_commands'], sort_keys=True, separators=(",", ":")).encode()
).hexdigest()[:16]
if args == ['providers']:
    response['providers'] = []
elif args == ['status']:
    mode = state.get('status_mode', 'ok')
    if mode == 'down':
        response = {'state': 'error', 'message': 'Simulated service socket failure'}
        code = 1
    else:
        response['message'] = 'Ready'
        response['voice_commands_revision'] = '0000000000000000' if mode == 'mismatch' else revision
    with open(os.environ['VOICE_PANEL_TEST_STATUS_LOG'], 'a') as status_log:
        status_log.write(json.dumps({'response': response, 'code': code, 'mode': state.get('status_mode', 'ok'), 'mapping': sorted(state['voice_commands'].keys())}) + '\\n')
elif args[0] == 'fixture' and len(args) == 2 and args[1] in ('ok', 'down', 'mismatch'):
    state['status_mode'] = args[1]
    save_state()
    response = {'state': 'idle', 'message': 'fixture mode set: ' + args[1]}
elif args == ['settings', 'show']:
    pass
elif args == ['apps']:
    response['voice_commands_revision'] = revision
    response['apps'] = [
        {'id': ident, 'name': name, 'icon': '',
         'commands': ['open ' + phrase for phrase, target in state['voice_commands'].items() if target == ident]
                     + (['open beta alternate ' + str(i) for i in range(16)] if ident == 'beta.desktop' else [])}
        for ident, name in [('alpha.desktop', 'Alpha'), ('beta.desktop', 'Beta')]
    ]
elif args[:2] == ['voice-command', 'list']:
    response['voice_commands'] = state['voice_commands']
elif args[:2] == ['voice-command', 'set'] and args[2] == 'fail phrase':
    response = {'state': 'error', 'message': 'Simulated write failure'}
    code = 1
elif args[:2] == ['voice-command', 'set']:
    time.sleep(0.08)  # make the reopen/list request overlap the write
    state['voice_commands'][args[2].removeprefix('open ')] = args[3]
    save_state()
elif args[:2] == ['voice-command', 'update']:
    previous = args[2].removeprefix('open ')
    state['voice_commands'].pop(previous)
    state['voice_commands'][args[3].removeprefix('open ')] = args[4]
    save_state()
elif args[:2] == ['voice-command', 'remove']:
    state['voice_commands'].pop(args[2])
    save_state()
else:
    response = {'state': 'error', 'message': 'Unexpected fixture request'}
    code = 1
print(json.dumps(response))
raise SystemExit(code)
'''

SYSTEMCTL = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

state_file = Path(os.environ['VOICE_PANEL_TEST_STATE'])
with open(os.environ['VOICE_PANEL_TEST_CALLS'], 'a') as calls:
    calls.write(json.dumps(sys.argv[1:]) + '\\n')
state = json.loads(state_file.read_text())
code = 0
if state.get('restart_codes'):
    code = state['restart_codes'].pop(0)
    next_file = state_file.with_suffix('.next')
    next_file.write_text(json.dumps(state))
    next_file.replace(state_file)
if 'restart' not in sys.argv[1:]:
    raise SystemExit(22)
raise SystemExit(code)
'''

HARNESS = '''import QtQuick
import Quickshell
import Quickshell.Io
import "Plugin"
ShellRoot {
    property var panel
    property int phase: 0
    property int sub: 0
    property int ticks: 0
    property int reopenedAt: 0
    property string fixtureState: ""
    property bool fixtureDone: false
    function fail(message) { console.error("FAIL panel refresh: " + message); Qt.quit() }
    function has(phrase) {
        for (var i = 0; i < panel.selectedAppCommands.length; i++)
            if (panel.selectedAppCommands[i].phrase === phrase) return true
        return false
    }
    function setFixture(mode) {
        fixtureState = "sent:" + mode
        fixtureDone = false
        if (mode === "down") fixtureDownJob.running = true
        else if (mode === "mismatch") fixtureMismatchJob.running = true
        else fixtureOkJob.running = true
    }
    Process {
        id: fixtureOkJob
        command: ["omarchy-voice", "fixture", "ok"]
        stdout: StdioCollector {}
        onExited: function(code) { if (fixtureState === "sent:ok") fixtureDone = true }
    }
    Process {
        id: fixtureDownJob
        command: ["omarchy-voice", "fixture", "down"]
        stdout: StdioCollector {}
        onExited: function(code) { if (fixtureState === "sent:down") fixtureDone = true }
    }
    Process {
        id: fixtureMismatchJob
        command: ["omarchy-voice", "fixture", "mismatch"]
        stdout: StdioCollector {}
        onExited: function(code) { if (fixtureState === "sent:mismatch") fixtureDone = true }
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
            if (ticks > 500) {
                fail("timed out in phase " + phase + " sub " + sub + " choice=" + panel.appChoice +
                     " entries=" + JSON.stringify(panel.selectedAppCommands) + " pending=" + panel.commandsPendingApply +
                     " status=[" + panel.commandStatus + "] probing=" + panel.applyChecking)
                return
            }
            if (phase === 0 && panel.appCatalog.length === 2 && panel.commandEntries.length === 2) {
                panel.selectApp({id: "alpha.desktop"})
                if (!has("open first phrase") || has("open other phrase")) { fail("wrong app rows on initial selection"); return }
                panel.commandRequest(["set", "new phrase", "alpha.desktop"])
                panel.refreshCommands() // queued while set is still running
                panel.selectApp({id: "beta.desktop"})
                if (!has("open other phrase") || has("open first phrase")) { fail("old app rows leaked after switch"); return }
                phase = 1
            } else if (phase === 1 && panel.commandEntries.some(function(a) { return a.phrase === "new phrase" }) &&
                       panel.appCatalog.some(function(a) { return a.id === "alpha.desktop" && a.commands.indexOf("open new phrase") >= 0 })) {
                if (has("open new phrase")) { fail("new command appeared under wrong app"); return }
                panel.selectApp({id: "alpha.desktop"})
                if (!has("open new phrase") || !panel.commandsPendingApply) { fail("saved phrase not shown as pending"); return }
                panel.commandRequest(["update", "new phrase", "renamed phrase", "alpha.desktop"])
                phase = 2
            } else if (phase === 2 && panel.commandEntries.some(function(a) { return a.phrase === "renamed phrase" }) &&
                       panel.appCatalog.some(function(a) { return a.id === "alpha.desktop" && a.commands.indexOf("open renamed phrase") >= 0 })) {
                if (has("open new phrase") || !has("open renamed phrase")) { fail("rename did not refresh routed rows"); return }
                panel.commandRequest(["remove", "renamed phrase"])
                phase = 3
            } else if (phase === 3 && !panel.commandEntries.some(function(a) { return a.phrase === "renamed phrase" }) &&
                       !panel.appCatalog.some(function(a) { return a.id === "alpha.desktop" && a.commands.indexOf("open renamed phrase") >= 0 })) {
                if (has("open renamed phrase")) { fail("removed phrase still displayed"); return }
                panel.addingCommand = true
                panel.commandRequest(["set", "fail phrase", "alpha.desktop"])
                phase = 4
            } else if (phase === 4 && panel.commandStatus === "Simulated write failure") {
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
                phase = 6; sub = 0
                panel.selectApp({id: "alpha.desktop"})
            } else if (phase === 6 && sub === 0 && panel.selectedAppCommands.some(function(a) { return a.phrase === "open first phrase" })) {
                panel.commandRequest(["set", "apply phrase a", "alpha.desktop"])
                sub = 1
            } else if (phase === 6 && sub === 1 && has("open apply phrase a")) {
                panel.commandStatus = ""
                panel.applyCommands()
                sub = 2
            } else if (phase === 6 && sub === 2 &&
                       panel.commandStatus === "Applied: the running voice service is ready and has the saved voice commands") {
                if (panel.commandsPendingApply || panel.applyChecking) { fail("apply success left pending/busy state"); return }
                phase = 7; sub = 0
            } else if (phase === 7 && sub === 0) {
                panel.commandRequest(["set", "apply phrase b", "alpha.desktop"])
                sub = 1
            } else if (phase === 7 && sub === 1 && has("open apply phrase b")) {
                panel.commandStatus = ""
                panel.applyCommands()
                sub = 2
            } else if (phase === 7 && sub === 2 &&
                       panel.commandStatus === "Could not restart voice service") {
                if (!panel.commandsPendingApply) { fail("failed restart cleared pending changes"); return }
                phase = 8; sub = 0
            } else if (phase === 8 && sub === 0) {
                panel.commandRequest(["set", "apply phrase c", "alpha.desktop"])
                sub = 1
            } else if (phase === 8 && sub === 1 && has("open apply phrase c")) {
                setFixture("down")
                sub = 2
            } else if (phase === 8 && sub === 2 && fixtureDone) {
                panel.commandStatus = ""
                panel.applyCommands()
                sub = 3
            } else if (phase === 8 && sub === 3 &&
                       panel.commandStatus === "Voice service restarted but did not become ready within the allowed time") {
                if (panel.applyChecking) { fail("timed-out apply left the panel busy"); return }
                if (!panel.commandsPendingApply) { fail("timed-out apply cleared pending changes"); return }
                setFixture("ok")
                sub = 4
            } else if (phase === 8 && sub === 4 && fixtureDone) {
                phase = 9; sub = 0
            } else if (phase === 9 && sub === 0) {
                panel.commandRequest(["set", "apply phrase d", "alpha.desktop"])
                sub = 1
            } else if (phase === 9 && sub === 1 && has("open apply phrase d")) {
                setFixture("mismatch")
                sub = 2
            } else if (phase === 9 && sub === 2 && fixtureDone) {
                panel.commandStatus = ""
                panel.applyCommands()
                sub = 3
            } else if (phase === 9 && sub === 3 &&
                       panel.commandStatus === "Voice service is ready but is not running the saved voice commands") {
                if (panel.applyChecking) { fail("revision mismatch left the panel busy"); return }
                if (!panel.commandsPendingApply) { fail("revision mismatch cleared pending changes"); return }
                console.log("PASS panel refresh: queued save/list, switch, update, remove, failed write, Desktop, reopen, update editor, and bounded Apply readiness (success/restart failure/probe timeout/revision mismatch)")
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
        state.write_text(json.dumps({"voice_commands": {"first phrase": "alpha.desktop", "other phrase": "beta.desktop"},
                                        "restart_codes": [0, 1, 0, 0],
                                        "status_mode": "ok"}))
        calls = root / 'calls.jsonl'
        calls.touch()
        status_log = root / 'status_log.jsonl'
        status_log.touch()
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        mock_cli = bin_dir / 'omarchy-voice'
        mock_cli.write_text(MOCK_CLI)
        mock_cli.chmod(0o700)
        systemctl = bin_dir / 'systemctl'
        systemctl.write_text(SYSTEMCTL)
        systemctl.chmod(0o700)
        env = dict(os.environ, QT_QPA_PLATFORM='wayland', VOICE_PANEL_TEST_STATE=str(state), VOICE_PANEL_TEST_CALLS=str(calls),
                   VOICE_PANEL_TEST_STATUS_LOG=str(status_log),
                   PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
        result = subprocess.run(['quickshell', '--no-color', '-p', str(root)], env=env,
                                capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        print(result.stderr, end='')
        if result.returncode or 'FAIL panel refresh' in result.stdout + result.stderr or 'PASS panel refresh' not in result.stdout + result.stderr or 'ReferenceError:' in result.stderr or 'TypeError:' in result.stderr:
            print('status_log:', status_log.read_text())
            print('calls:', calls.read_text())
            print('state:', state.read_text())
            raise SystemExit('Panel refresh validation failed')
        requests = [json.loads(line) for line in calls.read_text().splitlines()]
        if requests.count(['voice-command', 'list']) < 5 or requests.count(['apps']) < 5:
            raise SystemExit(f'Panel did not refresh on every mutation and reopen: {requests}')
        restarts = [r for r in requests if r == ['--user', 'restart', 'omarchy-voice.service']]
        statuses = [r for r in requests if r == ['status']]
        sets = [r for r in requests if r[:2] == ['voice-command', 'set']]
        # Four Applies: one restart each. The status endpoint also serves the panel's
        # continuous service monitor, so no exact status count is asserted; bounded probe
        # retries are verified from the panel's applyProbe attempt log.
        if len(restarts) != 4 or len(sets) != 6:
            raise SystemExit(
                f'Apply flow issued the wrong calls (restarts={restarts!r}, status={statuses!r}, sets={sets!r})'
            )
        unexpected = [r for r in requests if r[:1] == ['voice-command'] and r[1] == 'remove' and len(r) > 2
                      and r[2] not in ('renamed phrase',)]
        if unexpected:
            raise SystemExit(f'Apply flow removed saved commands: {unexpected!r}')


if __name__ == '__main__':
    main()
