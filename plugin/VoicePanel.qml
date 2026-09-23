import QtQuick
import QtQuick.Controls
import Quickshell
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
    readonly property color panelForeground: root.barForeground
    readonly property color panelDim: Qt.darker(root.barForeground, 1.4)
    readonly property string panelFont: bar ? bar.fontFamily : Style.font.family

    property string aliasStatus: ""
    property var aliasEntries: []
    property var appOptions: []
    property var appCatalog: []
    property int appPage: 0
    readonly property int appPageSize: 8
    property string appChoice: ""
    property string actionChoice: "app.launch"
    property string voiceInputMode: "record"
    property bool showSettings: false
    property string appSearchText: ""

    readonly property string selectedAppName: {
        for (var i = 0; i < appCatalog.length; i++)
            if (appCatalog[i].id === appChoice)
                return appCatalog[i].name
        return appLabelFor(appChoice)
    }

    readonly property var selectedAppAliases: {
        var out = []
        for (var i = 0; i < aliasEntries.length; i++)
            if (aliasEntries[i].desktopId === appChoice)
                out.push(aliasEntries[i])
        return out
    }

    readonly property var selectedAppCommands: {
        var rows = []
        if (appChoice === "")
            return rows
        var name = selectedAppName
        rows.push({ phrase: "Open " + name, action: "Launch " + name })
        for (var i = 0; i < selectedAppAliases.length; i++)
            rows.push({ phrase: "open " + selectedAppAliases[i].phrase, action: "Open " + name })
        return rows
    }

    readonly property var configuredAppIds: {
        var ids = {}
        for (var i = 0; i < aliasEntries.length; i++)
            ids[aliasEntries[i].desktopId] = true
        return ids
    }

    readonly property var filteredApps: {
        var q = appSearchText.toLowerCase()
        var configured = []
        var rest = []
        for (var i = 0; i < appCatalog.length; i++) {
            var app = appCatalog[i]
            if (q && String(app.name).toLowerCase().indexOf(q) < 0 && String(app.id).toLowerCase().indexOf(q) < 0)
                continue
            if (configuredAppIds[app.id])
                configured.push(app)
            else
                rest.push(app)
        }
        return configured.concat(rest)
    }
    readonly property int appPageCount: Math.max(1, Math.ceil(filteredApps.length / appPageSize))
    readonly property int clampedAppPage: Math.min(appPage, appPageCount - 1)
    readonly property var pagedApps: {
        var start = clampedAppPage * appPageSize
        return filteredApps.slice(start, start + appPageSize)
    }

    readonly property string heroMeta: {
        if (!voice.available && voice.voiceState === "error")
            return "Offline"
        if (voice.voiceState === "listening")
            return voice.aliasRecording ? "Recording alias" : "Listening"
        if (voice.voiceState === "transcribing")
            return "Transcribing"
        if (voice.voiceState === "executing")
            return "Running"
        if (voice.voiceState === "confirmation")
            return "Confirm"
        if (voice.voiceState === "alias_review")
            return "Review alias"
        if (voice.voiceState === "error")
            return "Error"
        return "Ready"
    }

    Component.onCompleted: {
        appQuery.running = true
        aliasRequest(["list"])
    }

    onOpenedChanged: if (root.opened && !appQuery.running) appQuery.running = true

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

    function appLabelFor(id) {
        for (var i = 0; i < appOptions.length; i++)
            if (appOptions[i].value === id)
                return appOptions[i].label
        return id
    }

    function setAliases(aliases) {
        var entries = []
        if (aliases) {
            for (var key in aliases) {
                if (typeof key !== "string" || typeof aliases[key] !== "string")
                    continue
                entries.push({ phrase: key, desktopId: aliases[key], appLabel: appLabelFor(aliases[key]) })
            }
        }
        aliasEntries = entries
    }

    function aliasRequest(args) {
        if (aliasCommand.running) return
        aliasCommand.command = ["omarchy-voice", "alias"].concat(args)
        aliasCommand.running = true
    }

    function showAliasesTab() {
        root.showSettings = false
    }

    function initials(name) {
        var text = String(name || "").replace(/[^A-Za-z0-9]+/g, "")
        return text.slice(0, 3).toUpperCase() || "?"
    }

    function iconSource(icon) {
        var value = String(icon || "")
        if (value.length === 0) return ""
        if (value.indexOf("file://") === 0 || value.indexOf("image://") === 0) return value
        if (value.charAt(0) === "/") {
            // Do not encode the empty segment before the leading slash.
            var parts = value.split("/")
            var encoded = []
            for (var i = 0; i < parts.length; i++)
                encoded.push(parts[i] === "" ? "" : encodeURIComponent(parts[i]))
            return "file://" + encoded.join("/")
        }
        var themed = Quickshell.iconPath(value, true)
        if (themed && themed.length > 0) return themed
        return ""
    }

    function selectApp(app) {
        if (!app || !app.id) return
        root.appChoice = app.id
        root.showSettings = false
    }

    VoiceModel {
        id: voice
        onConfirmationRequested: root.open()
        onAliasHeard: function(text) {
            phraseField.text = text
            root.showAliasesTab()
            root.open()
        }
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
                if (data.aliases) {
                    root.setAliases(data.aliases)
                } else if (aliasCommand.command.indexOf("list") < 0) {
                    root.aliasRequest(["list"])
                }
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
                var catalog = []
                for (var i = 0; i < data.apps.length; i++) {
                    var app = data.apps[i]
                    options.push({ value: app.id, label: app.name + " (" + app.id + ")" })
                    catalog.push({ id: app.id, name: app.name, icon: typeof app.icon === "string" ? app.icon : "" })
                }
                root.appOptions = options
                root.appCatalog = catalog
                root.appPage = 0
                root.setAliases(function() {
                    var current = {}
                    for (var j = 0; j < root.aliasEntries.length; j++)
                        current[root.aliasEntries[j].phrase] = root.aliasEntries[j].desktopId
                    return current
                }())
            } catch (e) {
                root.aliasStatus = "Could not list installed applications"
            }
        }
    }
    KeyboardPanel {
        id: popup
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: content
        contentWidth: popup.fittedContentWidth(Style.space(520))
        contentHeight: popup.fittedContentHeight(column.implicitHeight, Style.space(640))

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

                PanelHero {
                    width: parent.width
                    title: "Voice commands"
                    meta: root.heroMeta
                    detail: "LOCAL"
                    foreground: root.panelForeground
                    fontFamily: root.panelFont
                    iconOpacity: voice.voiceState === "error" ? 0.5 : 1.0
                    iconComponent: Component {
                        Text {
                            textFormat: Text.PlainText
                            text: "󰍬"
                            color: root.panelForeground
                            font.family: root.panelFont
                            font.pixelSize: Style.font.display
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: "Control the desktop with your voice. Hold " + root.shortcutLabel + ", speak, release. Speech stays on this machine."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: root.panelDim
                    font.family: root.panelFont
                    font.pixelSize: Style.font.caption
                }

                Text {
                    width: parent.width
                    visible: voice.message !== ""
                    text: voice.message
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: voice.voiceState === "error" ? Color.urgent : root.panelForeground
                    font.family: root.panelFont
                    font.pixelSize: Style.font.body
                }

                BorderSurface {
                    width: parent.width
                    visible: voice.voiceState === "confirmation"
                    implicitHeight: confirmationColumn.implicitHeight + Style.space(20)
                    color: "transparent"
                    radius: Style.cornerRadius
                    borderSpec: Border.controlSpec("normal", Color.urgent, Color.urgent)
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
                            color: root.panelForeground
                            font.family: root.panelFont
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
                    Button {
                        text: root.showSettings ? "Applications" : "Settings"
                        onClicked: root.showSettings = !root.showSettings
                    }
                }

                Column {
                    width: parent.width
                    spacing: Style.space(12)
                    visible: !root.showSettings

                    TextField {
                        id: appSearch
                        width: parent.width
                        placeholderText: "Search applications…"
                        onTextChanged: { root.appSearchText = text; root.appPage = 0 }
                    }
                    Text {
                        width: parent.width
                        visible: root.filteredApps.length === 0
                        text: root.appCatalog.length === 0
                              ? "Could not list installed applications yet."
                              : "No applications match that search."
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: root.panelDim
                        font.family: root.panelFont
                        font.pixelSize: Style.font.body
                    }

                    Flow {
                        width: parent.width
                        spacing: Style.space(8)
                        Repeater {
                            model: root.pagedApps
                            AppCard {
                                required property var modelData
                                appId: modelData.id
                                appName: modelData.name
                                appIcon: modelData.icon
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: Style.space(8)
                        visible: root.filteredApps.length > root.appPageSize
                        Button {
                            text: "Previous"
                            enabled: root.clampedAppPage > 0
                            onClicked: root.appPage = root.clampedAppPage - 1
                        }
                        Text {
                            text: "Page " + (root.clampedAppPage + 1) + " of " + root.appPageCount
                            textFormat: Text.PlainText
                            color: root.panelDim
                            font.family: root.panelFont
                            font.pixelSize: Style.font.caption
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Button {
                            text: "Next"
                            enabled: root.clampedAppPage < root.appPageCount - 1
                            onClicked: root.appPage = root.clampedAppPage + 1
                        }
                    }

                    Text {
                        width: parent.width
                        visible: root.appChoice === ""
                        text: "Click an application to see its voice commands and enroll an alias. This does not launch it."
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: root.panelDim
                        font.family: root.panelFont
                        font.pixelSize: Style.font.caption
                    }

                    Column {
                        width: parent.width
                        spacing: Style.space(12)
                        visible: root.appChoice !== ""

                        PanelSeparator { foreground: root.panelForeground }

                        PanelSectionHeader {
                            text: "COMMANDS · " + root.selectedAppName.toUpperCase()
                            foreground: root.panelForeground
                            fontFamily: root.panelFont
                        }
                        Repeater {
                            model: root.selectedAppCommands
                            CommandRow {
                                required property var modelData
                                width: parent.width
                                phrase: modelData.phrase
                                action: modelData.action
                            }
                        }

                        PanelSectionHeader {
                            text: "ALIASES"
                            foreground: root.panelForeground
                            fontFamily: root.panelFont
                        }
                        Text {
                            width: parent.width
                            text: "Record or type a phrase for " + root.selectedAppName + ". Recording never runs an action; review what was heard before saving."
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: root.panelDim
                            font.family: root.panelFont
                            font.pixelSize: Style.font.caption
                        }
                        Dropdown {
                            width: parent.width
                            label: "Action"
                            value: root.actionChoice
                            options: [{ value: "app.launch", label: "Open application" }]
                            onChanged: function(value) { root.actionChoice = value }
                        }
                        Dropdown {
                            width: parent.width
                            label: "Voice phrase"
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
                        }
                        Button {
                            text: "Apply saved aliases (restart voice service)"
                            enabled: !aliasRestart.running && !aliasCommand.running && !voice.busy &&
                                     (voice.voiceState === "idle" || voice.voiceState === "error" || voice.voiceState === "alias_review")
                            onClicked: aliasRestart.running = true
                        }
                        Text {
                            width: parent.width
                            visible: root.aliasStatus !== ""
                            text: root.aliasStatus + "\nAfter saving or removing an alias, click Apply to explicitly restart the voice service. This never changes the STT model or runs the recorded phrase."
                            textFormat: Text.PlainText
                            wrapMode: Text.WrapAnywhere
                            color: root.panelForeground
                            font.family: root.panelFont
                            font.pixelSize: Style.font.caption
                        }
                        Text {
                            width: parent.width
                            visible: root.selectedAppAliases.length === 0
                            text: "No spoken aliases saved for this app yet."
                            textFormat: Text.PlainText
                            color: root.panelDim
                            font.family: root.panelFont
                        }
                        Repeater {
                            model: root.selectedAppAliases
                            CommandRow {
                                required property var modelData
                                width: parent.width
                                phrase: "open " + modelData.phrase
                                action: "Open " + root.selectedAppName
                            }
                        }
                    }
                }

                Column {
                    width: parent.width
                    spacing: Style.space(12)
                    visible: root.showSettings

                    PanelSectionHeader {
                        text: "ACTIVATION"
                        foreground: root.panelForeground
                        fontFamily: root.panelFont
                    }
                    Text {
                        width: parent.width
                        text: "Hold " + root.shortcutLabel + " to talk; release to process. Activation is hold-to-talk only. Super+Ctrl+V remains Clipboard manager. Escape closes this panel, not the pending action."
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: root.panelForeground
                        font.family: root.panelFont
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
                        color: root.panelDim
                        font.family: root.panelFont
                        font.pixelSize: Style.font.caption
                    }

                    PanelSeparator { foreground: root.panelForeground }

                    PanelSectionHeader {
                        text: "PROVIDER"
                        foreground: root.panelForeground
                        fontFamily: root.panelFont
                    }
                    Text {
                        width: parent.width
                        text: "Local audio · faster-whisper. No cloud transcription provider in v0.1. Initial model download may require network access. Actions may launch networked apps."
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: root.panelForeground
                        font.family: root.panelFont
                    }
                    Text {
                        width: parent.width
                        text: voice.providerInfo
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        color: root.panelDim
                        font.family: root.panelFont
                        font.pixelSize: Style.font.caption
                    }

                    PanelSeparator { foreground: root.panelForeground }

                    PanelSectionHeader {
                        text: "CONFIGURATION"
                        foreground: root.panelForeground
                        fontFamily: root.panelFont
                    }
                    Text {
                        width: parent.width
                        text: "Settings: model, device, language and action permissions live in config.toml. Save the file and restart the voice service. Logs: ~/.local/state/omarchy-voice/voice.log"
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: root.panelForeground
                        font.family: root.panelFont
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

    component AppCard: BorderSurface {
        property string appId
        property string appName
        property string appIcon
        readonly property string resolvedIcon: root.iconSource(appIcon)
        readonly property bool selected: root.appChoice === appId
        readonly property bool configured: root.configuredAppIds[appId] === true

        width: Math.max(Style.space(110), Math.floor(((parent ? parent.width : Style.space(420)) - Style.space(24)) / 4))
        implicitHeight: appColumn.implicitHeight + Style.space(16)
        radius: Style.cornerRadius
        color: selected ? Style.selectedFillFor(root.panelForeground, Color.accent) : "transparent"
        borderSpec: Border.controlSpec(selected ? "selected" : "normal", root.panelForeground, Color.accent)

        Column {
            id: appColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(8)
            anchors.rightMargin: Style.space(8)
            spacing: Style.space(6)
            Text {
                width: parent.width
                text: appName
                textFormat: Text.PlainText
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
                color: root.panelForeground
                font.family: root.panelFont
                font.pixelSize: Style.font.caption
                font.bold: true
            }
            Text {
                width: parent.width
                visible: configured
                text: "Configured"
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                color: root.panelDim
                font.family: root.panelFont
                font.pixelSize: Style.font.caption
            }
            Item {
                width: Style.space(40)
                height: Style.space(40)
                anchors.horizontalCenter: parent.horizontalCenter
                Image {
                    id: appIconImage
                    anchors.fill: parent
                    visible: status === Image.Ready
                    source: resolvedIcon
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    cache: false
                    sourceSize.width: Math.max(1, Math.round(width * Screen.devicePixelRatio))
                    sourceSize.height: Math.max(1, Math.round(height * Screen.devicePixelRatio))
                }
                Text {
                    anchors.centerIn: parent
                    visible: appIconImage.status !== Image.Ready
                    text: root.initials(appName)
                    textFormat: Text.PlainText
                    color: root.panelForeground
                    font.family: root.panelFont
                    font.pixelSize: Style.font.body
                    font.bold: true
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.selectApp({ id: appId, name: appName, icon: appIcon })
        }
    }

    component CommandRow: BorderSurface {
        property string phrase
        property string action
        width: parent ? parent.width : Style.space(420)
        implicitHeight: row.implicitHeight + Style.space(12)
        radius: Style.cornerRadius
        color: "transparent"
        borderSpec: Border.controlSpec("normal", root.panelForeground, Color.accent)

        Row {
            id: row
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(8)
            Text {
                width: Math.max(Style.space(120), parent.width * 0.55)
                text: "“" + phrase + "”"
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: root.panelForeground
                font.family: root.panelFont
                font.pixelSize: Style.font.body
                font.bold: true
            }
            Text {
                width: Math.max(Style.space(80), parent.width * 0.45 - Style.space(8))
                text: action
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: root.panelDim
                font.family: root.panelFont
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignRight
            }
        }
    }
}
