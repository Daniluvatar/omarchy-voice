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

    VoiceModel {
        id: voice
        onConfirmationRequested: root.open()
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
                    text: "Hold Super+V to talk; release to process. Requires the opt-in keybinding. Escape closes this panel, not the pending action."
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
                    text: "Provider capabilities (reported by CLI)\n" + voice.providerInfo
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Color.foreground
                }
                Text {
                    width: parent.width
                    text: "Settings: model, device, language and action permissions live in config.toml. v0.1 does not provide live settings editing or pretend other providers work. Save the file and restart the voice service."
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
