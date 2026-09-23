import QtQuick
import Quickshell.Io

// One bounded CLI request at a time. Polling never overwrites an action argv.
Item {
    id: root
    property string voiceState: "idle"
    property string message: "Connecting to local voice service…"
    property string confirmationToken: ""
    property string aliasText: ""
    property bool aliasRecording: false
    property string providerInfo: "Local faster-whisper; querying capabilities…"
    property bool available: false
    property bool pollingEnabled: true
    readonly property bool busy: request.running || pendingAction.length > 0
    property string operation: ""
    property var pendingAction: []
    property bool providersPending: true
    property bool timedOut: false
    signal confirmationRequested()
    signal aliasHeard(string text)

    function fail(text) {
        available = false
        voiceState = "error"
        message = text
        confirmationToken = ""
    }
    function acceptStatus(data) {
        var states = ["idle", "listening", "transcribing", "executing", "confirmation", "alias_review", "error"]
        if (!data || states.indexOf(data.state) < 0 || typeof data.message !== "string")
            throw new Error("Invalid status response")
        if (data.state === "alias_review" && (typeof data.alias_text !== "string" || data.alias_text.length > 512))
            throw new Error("Invalid alias transcript")
        var token = data.state === "confirmation" && typeof data.confirmation_token === "string" ? data.confirmation_token : ""
        var fresh = token !== "" && token !== confirmationToken
        var newAlias = data.state === "alias_review" && typeof data.alias_text === "string" &&
                       (voiceState !== "alias_review" || aliasText !== data.alias_text)
        voiceState = data.state
        message = data.message
        confirmationToken = token
        aliasText = data.state === "alias_review" && typeof data.alias_text === "string" ? data.alias_text : ""
        if (data.state !== "listening" && data.state !== "transcribing") aliasRecording = false
        available = true
        if (fresh) confirmationRequested()
        if (newAlias) aliasHeard(aliasText)
    }
    function action(verb, token) {
        if (["start", "start-alias", "stop", "cancel", "confirm"].indexOf(verb) < 0 || pendingAction.length > 0) return
        if (verb === "confirm" && (!token || token !== confirmationToken || voiceState !== "confirmation")) return
        pendingAction = verb === "confirm" ? [verb, token] : [verb]
        if (verb === "start-alias") aliasRecording = true
        if (verb === "cancel" || verb === "start") aliasRecording = false
        // Remove authorization immediately to prevent duplicate clicks.
        if (verb === "confirm" || verb === "cancel") confirmationToken = ""
        pump()
    }
    function pump() {
        if (request.running) return
        var args
        if (pendingAction.length > 0) {
            args = pendingAction
            pendingAction = []
        } else if (providersPending) {
            args = ["providers"]
            providersPending = false
        } else {
            args = ["status"]
        }
        operation = args[0]
        timedOut = false
        request.command = ["omarchy-voice"].concat(args)
        request.running = true
        watchdog.restart()
    }
    function complete(code) {
        watchdog.stop()
        if (timedOut) {
            fail("Local service request timed out. Check the user service.")
        } else {
            try {
                var data = JSON.parse(output.text)
                if (operation === "providers") {
                    if (code !== 0 || !Array.isArray(data.providers)) throw new Error(data.message || "Provider query failed")
                    // Show exactly the advertised data, not invented selectable providers.
                    providerInfo = JSON.stringify(data.providers, null, 2)
                } else {
                    // The CLI returns exit 1 for a valid error-state response too.
                    acceptStatus(data)
                }
            } catch (e) {
                fail("Local voice CLI unavailable or invalid response: " + String(e) + " " + errors.text.trim().slice(0, 240))
            }
        }
        if (pendingAction.length > 0) Qt.callLater(pump)
    }
    Timer {
        interval: 750
        running: root.pollingEnabled
        repeat: true
        triggeredOnStart: true
        onTriggered: root.pump()
    }
    Timer {
        id: watchdog
        interval: 5000
        onTriggered: {
            root.timedOut = true
            request.running = false
            root.fail("Local service request timed out. Check the user service.")
        }
    }
    Process {
        id: request
        stdout: StdioCollector { id: output }
        stderr: StdioCollector { id: errors }
        onExited: function(exitCode) { root.complete(exitCode) }
    }
}
