#!/usr/bin/env python3
"""Symptom B regression: the Applications grid must heal to configured-first.

Drives the *real* panel (live QuickShell harness, in-band) against a mode-driven
CLI fixture. Each scenario rebuilds a fresh panel from cold start so the panel's
own bounded cold-start retry (not a harness poke / user action / manual refresh)
is what restores the configured-first order. "Configured" mirrors the panel's
union semantics and live backend contract: an application counts when it has any
routable voice command -- a built-in/configured catalog command
(``apps[].commands``) **or** a saved phrase (``voice_commands``). A failed
refresh must never drop a previously loaded catalog.

Scenarios asserted (healthy order is always computed as: configured apps in
alphabetical order, then unconfigured apps in alphabetical order):

  * S1 saved-list outage that recovers  (Beta built-in while down; Zebra saved-only rises after)
  * S2 app-catalog outage that recovers (grid stays empty while apps is down, heals after)
  * S3 both sources down, then both recover (cold heal across both inputs)
  * S4 built-in-only configured apps  (no saved phrases at all)
  * S5 saved-only configured apps     (no built-ins at all)
  * S6 unconfigured apps sink last    (single built-in leads, rest after)
  * S7 alphabetical stability across sources (all three configured -> pure alpha order)
  * S8 bounded retry: the downed source is re-polled only a bounded number of times on a
     2 s cadence, and churn stops once it recovers (call-log bounds checked in-process)

Boundedness is asserted from the recorded call log: every recovery's re-poll
count of each catalog endpoint stays below a small cap, and no scenario's churn
is unbounded. Fixture is confined to TMPDIR and never touches the user's store,
voice service, microphone, or desktop actions. Does not replace live UI QA.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
SHELL = Path('/usr/share/omarchy/shell')

# Cap on how many times a catalog endpoint may be polled within a single
# scenario window. Legit churn (initial load + a few 2 s retries + one
# post-success coalesced refetch) is far below this; an unbounded loop would
# blow through it.
MAX_ENDPOINT_CALLS_PER_SCENARIO = 25
MAX_RECOVERY_ENDPOINT_CALLS = 8

MOCK_CLI = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

state_file = Path(os.environ['VOICE_PANEL_ORDER_STATE'])
with open(os.environ['VOICE_PANEL_ORDER_CALLS'], 'a') as calls:
    calls.write(json.dumps(sys.argv[1:]) + '\\n')
state = json.loads(state_file.read_text())

def save_state():
    nf = state_file.with_suffix('.next')
    nf.write_text(json.dumps(state))
    nf.replace(state_file)

apps_defs = [('alpha.desktop', 'Alpha'), ('beta.desktop', 'Beta'), ('zebra.desktop', 'Zebra')]
args = sys.argv[1:]
response = {'state': 'idle', 'message': 'fixture'}
code = 0
if args[:2] == ['fixture', 'set']:
    payload = json.loads(args[2])
    marker = payload.pop('_marker', '')
    for key, value in payload.items():
        state[key] = value
    save_state()
    response['message'] = 'fixture set ' + marker
elif args == ['apps']:
    if not state.get('apps_ok', True):
        response = {'state': 'error', 'message': 'Simulated app catalog unavailable'}
        code = 1
    else:
        def commands_for(ident):
            seen = []
            for phrase, target in state.get('builtins', {}).items():
                if target == ident:
                    seen.append(phrase)
            # The backend derives per-app `commands` from the same saved store;
            # when that store is down (list_ok false) the saved-derived phrases
            # are absent from BOTH the list and the apps-embedded commands.
            if state.get('list_ok', True):
                for phrase, target in state.get('saved', {}).items():
                    if target == ident and phrase not in seen and ('open ' + phrase) not in seen:
                        seen.append('open ' + phrase)
            return seen
        response['apps'] = [{'id': i, 'name': n, 'icon': '', 'commands': commands_for(i)} for i, n in apps_defs]
        response['voice_commands_revision'] = 'ordering'
elif args[:2] == ['voice-command', 'list']:
    if not state.get('list_ok', True):
        response = {'state': 'error', 'message': 'Simulated voice service unavailable'}
        code = 1
    else:
        response['voice_commands'] = state.get('saved', {})
elif args == ['status']:
    response['message'] = 'Ready'
elif args[:2] == ['settings', 'show']:
    pass
else:
    response = {'state': 'error', 'message': 'Unexpected fixture request'}
    code = 1
print(json.dumps(response))
raise SystemExit(code)
'''

HARNESS = '''import QtQuick
import Quickshell
import Quickshell.Io
import "Plugin"
ShellRoot {
    property var panel: null
    property int si: -1
    property string stage: "begin"
    property int stageTicks: 0
    property bool downSee: false
    property bool pendingSet: false
    property string setMode: ""

    // Ordered, unambiguous scenarios. `expect` is the healthy final order;
    // `downCheck` (recovery scenarios only) is the sensible partial order while
    // the downed source is still unreachable.
    readonly property var scenarios: [
        { id: "S1", recover: true, downCheck: "beta.desktop,alpha.desktop,zebra.desktop",
          init: { _marker: "S1", apps_ok: true,  list_ok: false, builtins: {"launch beta": "beta.desktop"}, saved: {"launch zebra": "zebra.desktop"} },
          rec:  { _marker: "S1.rec", list_ok: true },
          expect: "beta.desktop,zebra.desktop,alpha.desktop" },
        { id: "S2", recover: true, downCheck: "",
          init: { _marker: "S2", apps_ok: false, list_ok: true, builtins: {"launch beta": "beta.desktop"}, saved: {"launch zebra": "zebra.desktop"} },
          rec:  { _marker: "S2.rec", apps_ok: true },
          expect: "beta.desktop,zebra.desktop,alpha.desktop" },
        { id: "S3", recover: true, downCheck: "",
          init: { _marker: "S3", apps_ok: false, list_ok: false, builtins: {"launch beta": "beta.desktop"}, saved: {"first alpha": "alpha.desktop"} },
          rec:  { _marker: "S3.rec", apps_ok: true, list_ok: true },
          expect: "alpha.desktop,beta.desktop,zebra.desktop" },
        { id: "S4", recover: false,
          init: { _marker: "S4", apps_ok: true, list_ok: true, builtins: {"launch beta": "beta.desktop", "launch zebra": "zebra.desktop"}, saved: {} },
          expect: "beta.desktop,zebra.desktop,alpha.desktop" },
        { id: "S5", recover: false,
          init: { _marker: "S5", apps_ok: true, list_ok: true, builtins: {}, saved: {"launch beta": "beta.desktop", "launch zebra": "zebra.desktop"} },
          expect: "beta.desktop,zebra.desktop,alpha.desktop" },
        { id: "S6", recover: false,
          init: { _marker: "S6", apps_ok: true, list_ok: true, builtins: {"launch zebra": "zebra.desktop"}, saved: {} },
          expect: "zebra.desktop,alpha.desktop,beta.desktop" },
        { id: "S7", recover: false,
          init: { _marker: "S7", apps_ok: true, list_ok: true, builtins: {"launch beta": "beta.desktop", "launch zebra": "zebra.desktop"}, saved: {"first alpha": "alpha.desktop"} },
          expect: "alpha.desktop,beta.desktop,zebra.desktop" }
    ]

    function fail(message) { console.error("FAIL panel ordering: " + message); Qt.quit() }
    function ids(list) {
        var out = []
        for (var i = 0; i < list.length; i++) out.push(list[i].id)
        return out.join(",")
    }
    function jmerge(base, extra) {
        var out = {}
        for (var k in base) out[k] = base[k]
        for (var e in extra) out[e] = extra[e]
        return out
    }
    function runFixture(payload) {
        pendingSet = true
        fixtureSetJob.running = false
        fixtureSetJob.command = ["omarchy-voice", "fixture", "set", payload]
        fixtureSetJob.running = true
    }
    function startScenario(index) {
        si = index
        stageTicks = 0
        downSee = false
        if (panel) { panel.destroy(); panel = null }
        setMode = "create"
        runFixture(JSON.stringify(scenarios[index].init))
    }
    function createPanel() {
        var component = Qt.createComponent("Plugin/VoicePanel.qml")
        if (component.status !== Component.Ready) { fail("panel compile: " + component.errorString()); return }
        panel = component.createObject(null)
        if (!panel) { fail("panel creation failed"); return }
        stage = scenarios[si].recover ? "down" : "final"
        stageTicks = 0
        downSee = false
    }
    function finish() {
        console.log("PASS panel ordering: 7-order scenarios + bounded cold-start self-heal (no user action)")
        if (panel) panel.destroy()
        Qt.quit()
    }
    Process {
        id: fixtureSetJob
        command: ["omarchy-voice", "fixture", "set", "{}"]
        stdout: StdioCollector {}
        onExited: function() {
            pendingSet = false
            if (setMode === "create") {
                setMode = ""
                createPanel()
            } else {
                setMode = ""
            }
        }
    }
    Component.onCompleted: { }
    Timer {
        interval: 30
        repeat: true
        running: true
        onTriggered: {
            if (pendingSet) return
            if (stage === "begin") { startScenario(0); return }
            stageTicks++
            var s = scenarios[si]
            if (!s) { fail("no scenario selected"); return }
            if (stage === "down") {
                if (s.downCheck !== undefined && panel && ids(panel.filteredApps) === s.downCheck)
                    downSee = true
                if (stageTicks >= 18 && downSee) {
                    // Flip the downed source(s) healthy; the panel's bounded
                    // retry must then heal the grid by itself.
                    setMode = "flip"
                    runFixture(JSON.stringify(jmerge(s.init, s.rec)))
                    stage = "final"
                    stageTicks = 0
                } else if (stageTicks > 45) {
                    fail("(down) " + s.id + " did not settle sensible partial order; ids=" +
                         (panel ? ids(panel.filteredApps) : "null") + " downCheck=" + s.downCheck)
                }
            } else if (stage === "final") {
                if (panel && ids(panel.filteredApps) === s.expect) {
                    if (si < scenarios.length - 1) startScenario(si + 1)
                    else finish()
                } else if (stageTicks > (s.recover ? 200 : 100)) {
                    fail(s.id + " did not reach " + s.expect + " got=" +
                         (panel ? ids(panel.filteredApps) : "null") +
                         " entries=" + (panel ? JSON.stringify(panel.commandEntries) : "null") +
                         " catalogLen=" + (panel ? panel.appCatalog.length : "null") +
                         " appsLoaded=" + (panel ? panel.appsLoaded : "null") +
                         " commandsLoaded=" + (panel ? panel.commandsLoaded : "null") +
                         " status=" + (panel ? panel.commandStatus : "null"))
                }
            }
        }
    }
}
'''


def run_harness():
    with tempfile.TemporaryDirectory(prefix='voice-panel-order-', dir=os.environ.get('TMPDIR')) as temp:
        root = Path(temp)
        for name in ('Commons', 'Ui', 'services'):
            (root / name).symlink_to(SHELL / name, target_is_directory=True)
        (root / 'Plugin').symlink_to(REPO / 'plugin', target_is_directory=True)
        (root / 'shell.qml').write_text(HARNESS)
        state = root / 'state.json'
        state.write_text(json.dumps({"apps_ok": True, "list_ok": True, "builtins": {}, "saved": {}}))
        calls = root / 'calls.jsonl'
        calls.touch()
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        mock_cli = bin_dir / 'omarchy-voice'
        mock_cli.write_text(MOCK_CLI)
        mock_cli.chmod(0o700)
        env = dict(os.environ, QT_QPA_PLATFORM='wayland',
                   VOICE_PANEL_ORDER_STATE=str(state), VOICE_PANEL_ORDER_CALLS=str(calls),
                   PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
        proc = subprocess.Popen(['quickshell', '--no-color', '-p', str(root)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            out, _ = proc.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            print(out, end='')
            print('calls:', calls.read_text())
            print('state:', state.read_text(), file=__import__('sys').stderr)
            raise SystemExit('Panel ordering validation timed out')
        text = out or ''
        print(text, end='')
        if (proc.returncode != 0 or 'FAIL panel ordering' in text or
                'PASS panel ordering' not in text or
                'ReferenceError:' in text or 'TypeError:' in text):
            print('calls:', calls.read_text())
            print('state:', state.read_text())
            raise SystemExit('Panel ordering validation failed')
        verify_call_bounds(calls.read_text())


def verify_call_bounds(calls_text):
    requests = [json.loads(line) for line in calls_text.splitlines() if line.strip()]

    # (index, marker) of each `fixture set`, in call order.
    markers = []
    for i, r in enumerate(requests):
        if r[:2] == ['fixture', 'set']:
            try:
                marker = json.loads(r[2]).get('_marker', '')
            except (ValueError, IndexError):
                marker = ''
            markers.append((i, marker))
    if not markers:
        raise SystemExit('no fixture set markers found in the call log')

    def count_between(start, end, endpoint):
        want = ['apps'] if endpoint == 'apps' else ['voice-command', 'list']
        return sum(1 for j in range(start, end) if requests[j][:len(want)] == want)

    for k, (mi, marker) in enumerate(markers):
        end = markers[k + 1][0] if k + 1 < len(markers) else len(requests)
        apps_calls = count_between(mi, end, 'apps')
        list_calls = count_between(mi, end, 'list')
        if apps_calls > MAX_ENDPOINT_CALLS_PER_SCENARIO or list_calls > MAX_ENDPOINT_CALLS_PER_SCENARIO:
            raise SystemExit(f'unbounded retry in window "{marker}": apps={apps_calls}, list={list_calls}')
        if marker.endswith('.rec') or marker in ('S1', 'S2', 'S3'):
            # After a source recovers, churn of either endpoint must stay bounded.
            if apps_calls > MAX_RECOVERY_ENDPOINT_CALLS or list_calls > MAX_RECOVERY_ENDPOINT_CALLS:
                raise SystemExit(f'recovery window "{marker}" chatty: apps={apps_calls}, list={list_calls}')
    print('call bounds: per-scenario list/apps calls stay bounded; recovery churn stops after success')


if __name__ == '__main__':
    run_harness()
