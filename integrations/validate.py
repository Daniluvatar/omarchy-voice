#!/usr/bin/env python3
"""Read-only integration checks; QML compilation uses installed Omarchy types.

Temporary harnesses live under TMPDIR, never in the user's configuration.
This does not install a plugin or start a microphone/desktop action.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
shell = Path('/usr/share/omarchy/shell')
subprocess.run(['omarchy', 'plugin', 'validate', str(repo / 'plugin')], check=True)
subprocess.run(['luac', '-p', str(repo / 'integrations/hyprland-bindings.lua')], check=True)
with tempfile.TemporaryDirectory(prefix='voice-qml-', dir=os.environ.get('TMPDIR')) as temp:
    root = Path(temp)
    for name in ('Commons', 'Ui', 'services'):
        (root / name).symlink_to(shell / name, target_is_directory=True)
    (root / 'Plugin').symlink_to(repo / 'plugin', target_is_directory=True)
    harness = '''import QtQuick
import Quickshell
import "Plugin"
ShellRoot {
    VoiceModel {
        id: model
        pollingEnabled: false
        property int heardCount: 0
        onVoiceCommandHeard: function(text) { heardCount++ }
    }
    VoiceModel {
        id: otherMonitor
        pollingEnabled: false
        property int heardCount: 0
        onVoiceCommandHeard: function(text) { heardCount++ }
    }
    Timer { interval: 100; running: true; onTriggered: Qt.quit() }
    Component.onCompleted: {
        var component = Qt.createComponent("Plugin/VoicePanel.qml")
        if (component.status !== Component.Ready) {
            console.error("FAIL panel compile: " + component.errorString())
            return
        }
        var panel = component.createObject(null)
        if (!panel) throw new Error("panel instantiation failed: " + component.errorString())
        panel.destroy()
        var states = ["idle", "listening", "transcribing", "executing", "confirmation", "error"]
        for (var i = 0; i < states.length; ++i) {
            model.acceptStatus({state: states[i], message: "test", confirmation_token: "test-token"})
            if (model.voiceState !== states[i]) throw new Error("state mismatch")
        }
        model.acceptStatus({state: "idle", message: "test"})
        if (model.confirmationToken !== "") throw new Error("stale token")
        model.voiceCommandRecording = true // This instance began the recording.
        otherMonitor.acceptStatus({state: "voice_command_review", message: "review", voice_command_text: "Open is putty high."})
        if (otherMonitor.heardCount !== 0) throw new Error("other monitor received voice command review")
        model.acceptStatus({state: "voice_command_review", message: "review", voice_command_text: "Open is putty high."})
        model.acceptStatus({state: "voice_command_review", message: "review", voice_command_text: "Open is putty high."})
        if (model.voiceCommandText !== "Open is putty high." || model.heardCount !== 1 || model.voiceCommandRecording)
            throw new Error("voice command text was lost or repeatedly emitted")
        model.acceptStatus({state: "idle", message: "test"})
        if (model.voiceCommandText !== "") throw new Error("stale voice command text")
        var invalidReview = false
        try { model.acceptStatus({state: "voice_command_review", message: "bad"}) } catch (e) { invalidReview = true }
        if (!invalidReview) throw new Error("missing transcript accepted")
        var rejected = false
        try { model.acceptStatus({state: "invented", message: "bad"}) } catch (e) { rejected = true }
        if (!rejected) throw new Error("invalid state accepted")
        model.fail("offline")
        if (model.available || model.voiceState !== "error" || model.voiceCommandRecording) throw new Error("offline not handled")
        console.log("PASS panel compilation and model state/token/error checks")
    }
}
'''
    (root / 'shell.qml').write_text(harness)
    env = dict(os.environ, QT_QPA_PLATFORM='wayland')
    try:
        result = subprocess.run(['quickshell', '--no-color', '-p', str(root)], env=env,
                                capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired as exc:
        print(exc.stdout, exc.stderr)
        raise SystemExit('QML validation timed out')
    print(result.stdout, end='')
    print(result.stderr, end='')
    if result.returncode or 'PASS panel compilation' not in result.stdout + result.stderr:
        raise SystemExit('QML validation failed')
subprocess.run([sys.executable, str(repo / 'integrations/validate_panel_refresh.py')], check=True)
subprocess.run([sys.executable, str(repo / 'integrations/validate_panel_ordering.py')], check=True)
subprocess.run([sys.executable, str(repo / 'integrations/validate_panel_async_order.py')], check=True)
print('PASS manifest, Lua syntax, native QML compilation, model and panel refresh/ordering/async checks')
