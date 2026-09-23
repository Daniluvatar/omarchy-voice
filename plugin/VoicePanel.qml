import QtQuick
import QtQuick.Controls
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
    id: root
    moduleName: "local.omarchy-voice"
    ipcTarget: "local.omarchy-voice"
    // Host owns IPC for bar widgets, as with built-in popup widgets.
    manageIpc: false
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    readonly property var shortcutOptions: [
        { value: "F5", label: "F5" },
        { value: "SUPER + SEMICOLON", label: "Super + ;" },
        { value: "SUPER + APOSTROPHE", label: "Super + '" },
        { value: "SUPER + GRAVE", label: "Super + `" },
        { value: "SUPER SHIFT + V", label: "Super + Shift + V (often misses release)" },
        { value: "SUPER + S", label: "Super + S (replaces scratchpad)" }
    ]
    readonly property string shortcutValue: root.settings && root.settings.shortcut ? String(root.settings.shortcut) : "F5"
    readonly property string shortcutLabel: {
        for (var i = 0; i < shortcutOptions.length; i++)
            if (shortcutOptions[i].value === shortcutValue)
                return shortcutOptions[i].label
        return shortcutValue.replace("SUPER", "Super").replace("SHIFT", "Shift")
    }
    property string aliasStatus: ""
    property string aliasList: ""
    property var appOptions: []
    property string appChoice: ""
    property string actionChoice: "app.launch"
    property string voiceInputMode: "record"
    Component.onCompleted: appQuery.running = true

    function applyShortcut(value) {
        var entry = { id: root.moduleName }
        if (root.settings) {
            for (var key in root.settings)
                if (key !== "id") entry[key] = root.settings[key]
        }
        entry.shortcut = value
        entry.activation = "Hold to talk"
        root.settings = entry
        if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
            root.bar.shell.updateEntryInline(root.moduleName, entry)
    }

    VoiceModel {
        id: voice
        onConfirmationRequested: root.open()
        onAliasHeard: function(text) { phraseField.text = text; root.open() }
    }
    WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "󰍬 Voice · " + voice.voiceState
        labelVisible: true
        foreground: voice.voiceState === "error" ? Color.urgent : root.barForeground
        onPressed: function(buttonCode) { root.toggle() }
    }
    Process {
        id: editor
        // Trusted, shipped helper; neither transcript nor settings become code.
        command: ["omarchy-voice-edit-config"]
    }
    Process {
        id: aliasCommand
        stdout: StdioCollector { id: aliasOutput }
        onExited: function(code) {
            try {
                var data = JSON.parse(aliasOutput.text)
                root.aliasStatus = data.message || "Alias request failed"
                if (code !== 0) return
                if (data.aliases) root.aliasList = JSON.stringify(data.aliases, null, 2)
            } catch (e) {
                root.aliasStatus = "Could not read alias response"
            }
        }
    }
    Process {
        id: aliasRestart
        command: ["systemctl", "--user", "restart", "omarchy-voice.service"]
        onExited: function(code) {
            root.aliasStatus = code === 0 ? "Voice service restarted; saved aliases are active" : "Could not restart voice service"
        }
    }
    Process {
        id: appQuery
        command: ["omarchy-voice", "apps"]
        stdout: StdioCollector { id: appOutput }
        onExited: function(code) {
            try {
                var data = JSON.parse(appOutput.text)
                if (code !== 0 || !Array.isArray(data.apps)) throw new Error("Invalid app list")
                var options = []
                for (var i = 0; i < data.apps.length; i++)
                    options.push({ value: data.apps[i].id, label: data.apps[i].name + " (" + data.apps[i].id + ")" })
                root.appOptions = options
            } catch (e) {
                root.aliasStatus = "Could not list installed applications"
            }
        }
    }
    function aliasRequest(args) {
        if (aliasCommand.running) return
        aliasCommand.command = ["omarchy-voice", "alias"].concat(args)
        aliasCommand.running = true
    }
    KeyboardPanel {
        id: popup
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: content
        contentWidth: popup.fittedContentWidth(Style.space(440))
        contentHeight: popup.fittedContentHeight(column.implicitHeight, Style.space(620))

        Flickable {
            id: content
            anchors.fill: parent
            clip: true
            contentWidth: width
            contentHeight: column.implicitHeight
            Keys.onEscapePressed: root.close()
            ScrollBar.vertical: ScrollBar {}
            Column {
                id: column
                width: content.width
                spacing: Style.space(12)
                Text {
                    width: parent.width
                    text: "Voice · " + voice.voiceState
                    textFormat: Text.PlainText
                    color: Color.foreground
                    font.pixelSize: Style.font.body
                    font.bold: true
                }
                Text {
                    width: parent.width
                    text: "LOCAL AUDIO · faster-whisper\nNo cloud transcription provider in v0.1. Initial model download may require network access. Actions may launch networked apps."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Color.foreground
                }
                Text {
                    width: parent.width
                    text: voice.message
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: voice.voiceState === "error" ? Color.urgent : Color.foreground
                }
                Text {
                    width: parent.width
                    text: "Hold " + root.shortcutLabel + " to talk; release to process. Activation is hold-to-talk only. Super+Ctrl+V remains Clipboard manager. Escape closes this panel, not the pending action."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Color.foreground
                }
                // A bounded confirmation surface in the native keyboard panel.
                // No Return/Space shortcut defaults to approval; focus stays on content.
                Rectangle {
                    width: parent.width
                    height: confirmationColumn.implicitHeight + Style.space(20)
                    visible: voice.voiceState === "confirmation"
                    color: "transparent"
                    border.color: Color.urgent
                    radius: Style.space(4)
                    Column {
                        id: confirmationColumn
                        anchors.centerIn: parent
                        width: parent.width - Style.space(20)
                        spacing: Style.space(8)
                        Text {
                            width: parent.width
                            text: "Confirm this action? Review the request above. Approval applies only to this pending token."
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: Color.foreground
                        }
                        Row {
                            spacing: Style.space(8)
                            Button {
                                text: "Deny / cancel"
                                enabled: !voice.busy
                                onClicked: voice.action("cancel", "")
                            }
                            Button {
                                text: "Confirm action"
                                enabled: !voice.busy && voice.confirmationToken !== ""
                                onClicked: voice.action("confirm", voice.confirmationToken)
                            }
                        }
                    }
                }
                Row {
                    spacing: Style.space(8)
                    Button {
                        text: "Start"
                        enabled: !voice.busy && voice.available && (voice.voiceState === "idle" || voice.voiceState === "error")
                        onClicked: voice.action("start", "")
                    }
                    Button {
                        text: "Stop"
                        enabled: !voice.busy && voice.voiceState === "listening"
                        onClicked: voice.action("stop", "")
                    }
                    Button {
                        text: "Cancel"
                        enabled: !voice.busy && voice.available && voice.voiceState !== "idle"
                        onClicked: voice.action("cancel", "")
                    }
                }
                Text {
                    width: parent.width
                    text: "Spoken app alias · Spotify example"
                    textFormat: Text.PlainText
                    color: Color.foreground
                    font.bold: true
                }
                Text {
                    width: parent.width
                    text: "Choose an installed app and an available action. Then record or type the phrase you want to use. Recording never runs an action; review what was heard before saving."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Color.foreground
                }
                SearchableDropdown {
                    width: parent.width
                    label: "1 · Application"
                    value: root.appChoice
                    options: root.appOptions
                    triggerLabel: root.appChoice === "" ? "Choose an installed app" : ""
                    onChanged: function(value) { root.appChoice = value }
                }
                Dropdown {
                    width: parent.width
                    label: "2 · Action"
                    value: root.actionChoice
                    options: [{ value: "app.launch", label: "Open application" }]
                    onChanged: function(value) { root.actionChoice = value }
                }
                Text {
                    width: parent.width
                    text: "Only opening an app is supported. Closing an app is not available; closing a window needs separate explicit confirmation."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Color.foreground
                }
                Dropdown {
                    width: parent.width
                    label: "3 · Voice phrase"
                    value: root.voiceInputMode
                    options: [
                        { value: "record", label: "Record and review a phrase" },
                        { value: "type", label: "Type a phrase" }
                    ]
                    onChanged: function(value) { root.voiceInputMode = value }
                }
                Row {
                    visible: root.voiceInputMode === "record"
                    spacing: Style.space(8)
                    Button {
                        text: "Record alias"
                        enabled: root.appChoice !== "" && !voice.busy && voice.available &&
                                 (voice.voiceState === "idle" || voice.voiceState === "error" || voice.voiceState === "alias_review")
                        onClicked: voice.action("start-alias", "")
                    }
                    Button {
                        text: "Finish alias recording"
                        enabled: !voice.busy && voice.voiceState === "listening" && voice.aliasRecording
                        onClicked: voice.action("stop", "")
                    }
                }
                TextField {
                    id: phraseField
                    width: parent.width
                    placeholderText: "Heard phrase or alias (e.g. open music app) — review before saving"
                }
                Row {
                    spacing: Style.space(8)
                    Button {
                        text: "Save alias"
                        enabled: !aliasCommand.running && phraseField.text.trim() !== "" && root.appChoice !== "" && root.actionChoice === "app.launch"
                        onClicked: root.aliasRequest(["set", phraseField.text, root.appChoice])
                    }
                    Button {
                        text: "Remove alias"
                        enabled: !aliasCommand.running && phraseField.text.trim() !== ""
                        onClicked: root.aliasRequest(["remove", phraseField.text.toLowerCase().replace(/^(open|launch|start)\s+/, "").replace(/[.?!]$/, "")])
                    }
                    Button {
                        text: "Show aliases"
                        enabled: !aliasCommand.running
                        onClicked: root.aliasRequest(["list"])
                    }
                }
                Button {
                    text: "Apply saved aliases (restart voice service)"
                    enabled: !aliasRestart.running && !aliasCommand.running && !voice.busy &&
                             (voice.voiceState === "idle" || voice.voiceState === "error" || voice.voiceState === "alias_review")
                    onClicked: aliasRestart.running = true
                }
                Text {
                    width: parent.width
                    text: root.aliasStatus + (root.aliasList ? "\n" + root.aliasList : "") + "\nAfter saving or removing an alias, click Apply to explicitly restart the voice service. This never changes the STT model or runs the recorded phrase."
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Color.foreground
                }
                Text {
                    width: parent.width
                    text: "Provider capabilities (reported by CLI)\n" + voice.providerInfo
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Color.foreground
                }
                Dropdown {
                    width: parent.width
                    label: "Voice shortcut"
                    value: root.shortcutValue
                    options: root.shortcutOptions
                    onChanged: function(value) { root.applyShortcut(value) }
                }
                Text {
                    width: parent.width
                    text: "This dropdown only updates the panel label. Hyprland still needs the matching hold/release binding. Current binding is F5. F9 stays Voxtype. Super+Ctrl+V remains Clipboard manager."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Color.foreground
                }
                Text {
                    width: parent.width
                    text: "Settings: model, device, language and action permissions live in config.toml. Save the file and restart the voice service. Logs: ~/.local/state/omarchy-voice/voice.log"
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Color.foreground
                }
                Button {
                    text: "Open configuration…"
                    enabled: !editor.running
                    onClicked: editor.running = true
                }
            }
        }
    }
}
