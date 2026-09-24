# Native Omarchy Shell integration (v0.1)

Nothing in this repository installs itself. The commands below are **manual,
opt-in changes**. Development/validation does not modify `/usr/share/omarchy`,
`~/.config`, the running shell, Hyprland bindings, or voxtype.

## Requirements and contract

This targets the installed Lua-configured Omarchy / Quickshell shell API:
`qs.Ui.Panel`, `WidgetButton`, `KeyboardPanel`, and `qs.Commons`. The manifest
uses schema 1 and third-party ID `local.omarchy-voice` (`omarchy.*` is reserved).
`plugin/` is the plugin root, not the repository root. Do not use `omarchy plugin
add` against this repository: that command expects a root manifest.

Install the Python backend and local STT dependency using the repository README.
The supplied unit expects an executable at `~/.local/bin/omarchy-voice`; the
shell and Hyprland also need that directory on PATH. Confirm before enabling:

```sh
command -v omarchy-voice
omarchy-voice providers
omarchy-voice doctor
```

The frontend executes literal argv arrays, never a transcript-derived shell
command. It reads `omarchy-voice providers` once on widget creation, then polls
`omarchy-voice status` every 750 ms. It serializes CLI requests, queues at most
one action behind a poll, and bounds requests with a five-second watchdog.
Controls call `start`, `stop`, `cancel`, and `confirm TOKEN`. Each status/action
response must be a single JSON object on stdout:

```json
{"state":"confirmation","message":"Review this action","confirmation_token":"opaque-token"}
```

States: `idle`, `listening`, `transcribing`, `executing`, `confirmation`, `error`.
`message` must be a string. The token is optional except for confirmation;
without one the approval button is disabled. Exit 1 with valid error JSON is
supported. Provider responses must contain a `providers` array. Backend
capabilities are displayed verbatim, not turned into fictional provider choices.

## Install manually

Run from the repository root, after reviewing the files. If the target plugin
already exists, use the update procedure instead of merging directories.

```sh
omarchy plugin validate ./plugin
mkdir -p "$HOME/.config/omarchy/plugins"
# Stop here if this directory already exists.
test ! -e "$HOME/.config/omarchy/plugins/local.omarchy-voice" && \
  cp -R ./plugin "$HOME/.config/omarchy/plugins/local.omarchy-voice"
install -Dm755 integrations/omarchy-voice-edit-config "$HOME/.local/bin/omarchy-voice-edit-config"
install -Dm644 integrations/omarchy-voice.service "$HOME/.config/systemd/user/omarchy-voice.service"
systemctl --user daemon-reload
systemctl --user enable --now omarchy-voice.service
omarchy plugin enable local.omarchy-voice
omarchy bar put local.omarchy-voice --section right --index 0
```

If using a non-default XDG config directory, substitute it for `~/.config` in
these commands. If your backend executable is elsewhere, explicitly edit the
copied unit's `ExecStart` before starting it. Do not run both a manual `serve`
and this unit. The unit follows the graphical session and inherits the user
manager's session environment. If desktop commands cannot connect, inspect
`systemctl --user show-environment` for `WAYLAND_DISPLAY` and
`HYPRLAND_INSTANCE_SIGNATURE`; do not hard-code another session's values.

The widget is a bar widget, not a background service: it polls only while the
bar loads it. The backend operates independently. Removing/hiding the widget
does not stop capture. Multiple monitor bars may instantiate separate readers;
a pending token can consequently appear on more than one display. Authorization
must remain one-shot and expire in the backend.

## F5 hold-to-talk

**Stock F5 is unused on this Omarchy install.** F9 stays Voxtype dictation.
Super+V stays Universal paste. Super+Ctrl+V stays Clipboard manager. Super+S
stays Toggle scratchpad. Super+; is left alone. Super+Shift+V is a poor
hold-to-talk chord: releasing Shift before V often never fires `stop`. First
inspect `omarchy menu keybindings --print`. Review
`integrations/hyprland-bindings.lua` and copy its lines into
`~/.config/hypr/bindings.lua`. It calls `hl.unbind("F5")` before the
press/release pair. The installed `o.bind` helper forwards `{ release = true }`
to `hl.bind`; the stock F9 voxtype binding uses the same API.

This integration does not change **F9**, **Super+V**, **Super+Ctrl+V**,
**Super+S**, **Super+Ctrl+X**, or voxtype. Do not hold both dictation shortcuts
concurrently. If release is missed, the backend capture limit bounds recording;
use Cancel. After making your own binding edit, run:

```sh
hyprctl reload
hyprctl configerrors
```

Do not apply this Lua snippet to an older `.conf`-configured Hyprland without
adapting and checking that version's API.

## UI, privacy, and settings

The bar shows the actual backend state. Click it for status, controls, provider
capabilities and settings. Widget settings expose a preferred hold-to-talk
shortcut and document that activation is hold-to-talk only. Changing the
shortcut label does **not** rewrite Hyprland; copy the matching lines from
`integrations/hyprland-bindings.lua` after editing the key. Toggle, wake-word,
and always-listening modes are not implemented. A new confirmation token opens
the native panel with
an explicit **Deny / cancel** and **Confirm action** surface. There is no
voice-only confirmation or automatic approval. Escape/outside-click merely
closes the panel; the pending operation remains subject to backend expiry.
Approval is disabled immediately after clicking and when the token disappears.

Only local **faster-whisper** is implemented. The local badge describes audio
transcription, not a network firewall: initial model downloads need network
access, and authorized actions can launch networked apps. The frontend does not
persist audio and renders backend text as plain text. Explicitly approved alias
text is saved in the user configuration; ordinary transcripts remain in the
local backend diagnostic log. Inspect its retention and permission policy
independently.

Select an installed app to see **Voice commands → Current configured commands**:
built-in/configured `open …` routes that actually resolve to that app and saved
panel phrases. Click **New command** to reveal the **Voice phrase** choice
(record-and-review or type). For Spotify, press **●** to record, speak, then
**■** to finish. Review/edit the heard text before **✓** to save, or type
a phrase instead. The only app action is **Open application**; closing an app is
not supported, and closing a window still requires the distinct confirmation
workflow. The audio is deleted; reviewed phrase-to-desktop-ID mappings are
stored in `$XDG_CONFIG_HOME/omarchy-voice/aliases.json` and only become active
after an explicit service restart via **Apply saved phrases** (or
`systemctl --user restart omarchy-voice.service`). With the app-scope backend
fix installed, voice-launched apps survived a live restart; see issue #4 for
verification details. Each saved command has a pencil (✎) on the right to edit/record a replacement phrase (stored atomically, without overwriting a different saved phrase), and a remove (×) icon that switches to confirm (✓) with a cancel (↶) icon. Built-in and TOML commands have no edit/remove icons; to change a TOML alias, edit its configuration instead. Earlier Spotify-specific hard-coded mishear phrases were removed; explicitly enroll an exact phrase if transcription requires one. These controls manage
only the panel's mappings. This is exact matching,
not STT model training or fuzzy launch. The existing diagnostic log still
contains local transcriptions.

“Open configuration…” invokes the shipped fixed helper argv. It opens
`$XDG_CONFIG_HOME/omarchy-voice/config.toml` (default
`~/.config/omarchy-voice/config.toml`) with `omarchy launch config editor`.
The helper creates only the parent directory when explicitly invoked;
it does not overwrite an existing file. A missing/empty TOML uses backend
defaults. Example settings to enter (check README for the full current schema):

```toml
[stt]
provider = "faster-whisper"
model = "tiny.en"
device = "cpu"
compute_type = "int8"
language = "en"

[audio]
max_seconds = 15

[confirmation]
timeout_seconds = 15

# Start with all desktop execution disabled; opt in to documented action IDs.
[permissions]
allow = []
```

v0.1 has **no live configuration API for general settings**, model downloader UI,
microphone chooser, waveform, or in-panel permissions editor. The panel does
have a provider selector and reviewed app-alias enrollment and
removal; it does not change action permissions. Save the file, cancel any
capture, then run
`systemctl --user restart omarchy-voice.service`. Recreate/reload the widget to
refresh cached provider capabilities if dependencies change.

## Validate without installing

```sh
python3 integrations/validate.py
/usr/lib/qt6/bin/qmllint plugin/VoiceModel.qml
systemd-analyze --user verify integrations/omarchy-voice.service
```

The Python validator uses the installed manifest validator, `luac -p`, and a
temporary Quickshell harness importing the actual installed shell types. It
compiles (does not instantiate/show) the panel and exercises model state,
malformed state, stale token clearing and offline handling using explicit test
fixtures. It needs a working Wayland connection: Qt's offscreen platform cannot
load Quickshell's native `PanelWindow` backend. No microphone, STT, desktop action,
or installation occurs. The fixture checks are not an end-to-end audio test.

Standalone qmllint cannot resolve `qs.*` without the shell import environment;
the native component compilation is the authoritative type-loading check here.
Qt's shipped Process metadata may also warn about `QProcess::ExitStatus` despite
successful native compilation. Unit verification can warn that ExecStart is
absent before the backend is installed at the documented user path.

Live acceptance still requires explicit user testing: install, ensure microphone
permission and local model availability, hold/release the shortcut, inspect
listening → transcribing → executing/idle, deny/approve a harmless test request,
check expiry/error recovery, and verify popup focus/placement on each monitor.
For aliases, record a Spotify example without executing, review the heard text,
save it, click **Apply saved phrases** only after protecting work in voice-launched apps, then speak the alias and confirm the actual app
appears. No live alias enrollment, model inference or disruptive action has been
claimed tested by the automated harness.

## Update and uninstall

For an update, stop capture with `omarchy-voice cancel`, disable the widget with
`omarchy plugin disable local.omarchy-voice`, back up its directory outside the
plugin discovery directory, and replace that directory with a fresh copy of
`plugin/`. Validate the replacement and enable the widget again. Reinstall the
helper/unit if changed, run `systemctl --user daemon-reload`, and restart the
service. Update the Python backend separately using the README procedure.
Manual copies are **not** tracked by `omarchy plugin update`.

To uninstall:

1. Cancel any capture and run `systemctl --user disable --now omarchy-voice.service`.
2. Run `omarchy plugin disable local.omarchy-voice`; remove only
   `~/.config/omarchy/plugins/local.omarchy-voice` after checking its path.
3. Remove the copied `~/.config/systemd/user/omarchy-voice.service` and
   `~/.local/bin/omarchy-voice-edit-config`, then run
   `systemctl --user daemon-reload`.
4. Remove the three opt-in Lua binding lines and reload/check Hyprland. Super+S
   should already be Toggle scratchpad; F5 should become unbound.
5. Remove the Python tool separately if desired. Keep or explicitly remove the
   voice TOML and model cache; neither should be deleted silently.

No uninstall step should modify F9/voxtype or any packaged Omarchy files.
