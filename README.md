# Omarchy Voice

Local-first voice commands for Omarchy. **v0.1 architectural MVP, not a finished public product.** Python handles audio, speech recognition and permission-checked actions; a native Omarchy Shell widget presents status and confirmation.

```text
Hold F5 → PipeWire → local Faster-Whisper → deterministic intent
                                                    ↓
                                permission check → registered desktop action
                                                    ↑
                               Omarchy widget / explicit close confirmation
```

## Current implementation

- Independent PipeWire capture with bounded duration and temporary WAV cleanup.
- Local Faster-Whisper adapter, offline inference after an explicit model download, CPU/int8 defaults; optional CUDA configuration.
- Replaceable STT contract and injected test provider; no dependency on Voxtype.
- Deterministic English parsing, installed `.desktop` app discovery and configurable exact aliases.
- Native-panel enrollment of reviewed spoken app aliases: a bounded recording transcribes without executing, or a phrase can be typed; the user explicitly maps the text to an installed app. No training audio is saved.
- Strict action/parameter validation, action permissions, expiring single-use nonvoice confirmation for window closing. No arbitrary shell, shutdown or reboot action.
- Unix-socket daemon with owner-only runtime permissions, bounded requests, duplicate-instance protection, cancellation and killable transcription worker.
- JSON CLI, dry-run command planning, diagnostics, model download, and `omarchy-voice logs` for the local diagnostic file.
- Native Omarchy bar widget/panel: opens on a paginated application grid. **Applications** and **Desktop** are separate catalogs. Desktop lists real window/workspace/system phrases (close, monitor move, workspace switch/move, mute, lock) — not Super+K swap-window chords, which voice does not run. Clicking an app shows **Voice commands → Current configured commands** underneath: exact built-in/configured app-launch phrases that resolve to that installed app, plus saved panel phrases, each listed once. **New command** reveals the record-or-type form; the only app action is **Open application**. After recording on a multi-monitor bar, only the widget that initiated recording reopens for review. Settings is a separate screen from a button next to Start/Stop. Settings **Provider** is a dropdown (v0.1: faster-whisper only); Model, Device and Language appear from that provider’s capabilities. Saving STT writes `config.toml` and needs an explicit service restart.
- After a successful spoken action that has a Super+K chord, show the same bottom-center Omarchy OSD used when launching an app, with **only the keybinding** (`SUPER + RETURN`, `SUPER + 4` for workspace switch, `SUPER SHIFT + 4` for move-window-to-workspace). Settings includes a **Show keybinding** toggle (on by default); turning it off skips the overlay immediately. Chords are refreshed from `omarchy menu keybindings --print`. Actions without a chord, or relative “next/left workspace” moves, show no OSD.
- Opt-in systemd user service and Lua hold-to-talk bindings; existing F9/Voxtype remains independent.

### Supported commands

| Spoken command | Result |
| --- | --- |
| Open Brave / Open terminal / Open Spotify | Launch an installed application (terminal uses Omarchy’s default terminal) |
| Open / launch / start `<application>` | Exact installed name or configured alias |
| Close window | Request explicit confirmation |
| Move this / this window / the window left or right | Move the focused window to that monitor |
| Move this window to the other screen | Move the focused window to the other monitor |
| Switch / move to workspace four | Move the focused window to workspace 4 |
| Move window to the left / right / next / previous workspace | Move the focused window one workspace over |
| Workspace one / two / … / ten | Switch focus to workspace 1–10 |
| Volume up / Volume down | Adjust output volume |
| Mute | Toggle output mute |
| Lock computer | Lock the desktop |

Ordinary single sentence-ending punctuation from STT is accepted. Unknown/ambiguous commands fail safely. Spoken **open terminal**, **open the terminal**, **open term**, **open termina**, **open terminator**, and **open ghostty** run `omarchy launch terminal` unless you configure a `terminal` desktop alias. Spoken **open browser** / **open brave** / **open brave browser** / **open chromium** map to Brave. Spotify's default is **open spotify**; earlier hard-coded STT mishearings (**open a Spotify**, **open and Spotify**, **open is Spotify**) are no longer accepted by default. Any exact mishearing such as **open is putty high** can instead be reviewed and explicitly mapped to Spotify in the native panel; **open music app** is a user-chosen alias. A comma after Open (`Open, brave.`) is ignored. Window moves accept a small set of natural phrases (`move this window to the left`, `move it to the other screen`, `switch to workspace four`, `move window to the left workspace`) and still use the window focused when you press F5. **Move … left/right** without `workspace` is a monitor move; **… left/right workspace** is a workspace move. Common STT mishears such as **water space** / **world space** and **for** / **forward** for four are normalized. Numbered window labels and app names are rejected. `app.close` is not implemented: only closing a window is supported. Volume directions use the shared `audio.volume` action with validated parameters, rather than separate action IDs in the proposal.

Application launches use validated argv without a shell, detached standard streams and a new process session. `systemd-run --user --scope` hands the launcher to a transient scope outside the voice service cgroup before it launches an app; if the user manager cannot create the scope, the command fails rather than falling back to an unsafe service child. The backend watches the scope launcher for up to 250 ms: missing executables and immediate nonzero exits fail; a still-running launcher is accepted and reaped asynchronously when it exits, without a lifetime timeout or termination. Acceptance is not proof that a window appeared; failures after the startup window are not reported to the UI. An isolated service-stop probe and a live voice-launched Brave process surviving a service restart verified the process boundary; the user separately reported that Spotify phrase Apply left voice-opened apps running. Other desktop actions retain their 10-second command timeout. See [ADR 0004](docs/adr/0004-app-launch-scopes.md).

## Install backend

Requirements: Linux graphical session with Omarchy/Hyprland, a running systemd user manager (`systemd-run`), PipeWire `pw-record`, `wpctl`, `gio`, and `uv`. Python **3.12 is the tested runtime**; `uv` manages it without modifying system Python. CUDA is optional and untested. The native frontend targets the installed Omarchy 4.0.4-1 shell and Hyprland 0.56.2 Lua API, not older `.conf` configurations.

```sh
git clone https://github.com/Daniluvatar/omarchy-voice.git
cd omarchy-voice
uv tool install --python 3.12 --from '.[stt]' omarchy-voice
# Ensure ~/.local/bin is on PATH.
omarchy-voice --help
omarchy-voice doctor
omarchy-voice download-model
```

The repository is currently private; cloning requires access through your GitHub credentials. `download-model` downloads the configured model (default `tiny.en`) into the Hugging Face cache. That step needs Internet access; transcription then uses locally cached files and does not send microphone audio to a service. `doctor` checks dependencies, not model readiness; actual transcription validates the model.

### Configuration

Optional path: `~/.config/omarchy-voice/config.toml` (respects `XDG_CONFIG_HOME`). To create it without overwriting an existing file:

```sh
mkdir -p ~/.config/omarchy-voice
test -e ~/.config/omarchy-voice/config.toml || cp examples/config.toml ~/.config/omarchy-voice/config.toml
```

Review [examples/config.toml](examples/config.toml) before enabling the daemon. **Defaults allow the supported actions**, including desktop locking; window closing still requires confirmation. To deny all execution during setup:

```toml
[permissions]
allow = []
```

Allowed action IDs: `app.launch`, `window.close`, `window.move_monitor`, `window.move_workspace`, `workspace.switch`, `audio.volume`, `audio.mute`, `system.lock`. Unknown settings and action IDs are rejected. App aliases must match actual installed desktop IDs; the example IDs are not a promise that those apps are installed. Edit `[applications.aliases]` to match your installation, or use the native panel's **Voice commands** section / CLI to save a reviewed text mapping. Panel phrases (stored as aliases) live separately in `~/.config/omarchy-voice/aliases.json` (respects `XDG_CONFIG_HOME`) and take precedence over duplicate TOML aliases. Select a searchable **Application** (from installed desktop entries): its current configured commands list verified `open …` routes, not every possible verb or unconfigured app name. For example, Brave can show **open browser** and **open brave**, and Spotify **open spotify** and a saved **open music app**, if those apps/routes exist locally. Click **New command**, choose **Voice phrase** (record-and-review or type), then use the **● record**, **■ finish**, and **✓ save** icon buttons; their descriptions appear on hover. The only app action is **Open application**; it is displayed as text, not a selectable action menu. Then explicitly click **Apply saved phrases** to restart the service. Recording never runs its transcript as a command. Closing an application is not implemented; window closing remains a separate confirmation-gated action, not an app phrase option. Default capture limit is 15 seconds, STT timeout 60 seconds, confirmation expiry 15 seconds. Panel Settings can set **Provider** (faster-whisper only), **Model**, **Device** and **Language** through `omarchy-voice settings stt`; that writes `[stt]` in `config.toml` and needs an explicit **Apply STT** / service restart. Other keys (permissions, capture limits) still need the TOML editor. Configuration or alias changes require restarting the daemon; saving a phrase or STT setting alone does not restart it. With the installed app-scope backend, voice-launched apps survived Apply in a live test; restart still interrupts any ongoing voice capture. `--config PATH` is a global option **before** the subcommand.

Saved panel phrases have a **pencil (✎)** and **remove (×)** icon on the right of each command row. The pencil opens the reviewed phrase editor and atomically replaces the old saved mapping; the remove icon switches to a confirm (✓) icon while the pencil switches to cancel (↶). Built-in phrases and aliases from `config.toml` are read-only in this panel; create a new phrase or edit configuration separately. **New command** remains below the list. **Apply saved phrases** stays available beneath the form even when no new command is being entered and explicitly restarts the service after a change. The CLI equivalent is `omarchy-voice alias update 'music app' 'open favorite music' spotify.desktop`.

## Run without installing the desktop integration

First inspect commands without changing the desktop:

```sh
omarchy-voice parse 'workspace two'
omarchy-voice run 'workspace two'             # Dry run: prints validated argv
omarchy-voice run 'open terminal'             # Dry run: omarchy launch terminal
omarchy-voice alias set 'open music app' Spotify # Save exact phrase; no app launched
omarchy-voice alias list
omarchy-voice alias remove 'music app'           # Undo the alias
omarchy-voice transcribe /absolute/path/command.wav  # Real local STT, dry-run action
```

File transcription accepts bounded PCM WAV audio within the configured capture limit. Unsupported recognized speech returns an error and does not execute anything.

Start a daemon in one terminal:

```sh
omarchy-voice serve
```

In another terminal, **these commands activate your microphone and execute a recognized permitted command**:

```sh
omarchy-voice start
# Speak a supported command.
omarchy-voice stop
omarchy-voice status
omarchy-voice cancel
omarchy-voice logs
```

`stop` ends capture and begins processing; it does **not** shut down the daemon. Ctrl+C in its terminal shuts down `serve` and cleans up. Only one daemon may run per user runtime directory. Diagnostic lines, including the recognized transcript, are appended to `~/.local/state/omarchy-voice/voice.log`. Use `omarchy-voice logs` or `omarchy-voice cancel` to inspect or clear a leftover error.

Explicit text/file execution requires the daemon:

```sh
omarchy-voice run 'workspace two' --execute
omarchy-voice transcribe /absolute/path/command.wav --execute
```

Execution uses the daemon's configuration. The default for `run` and `transcribe` is dry-run; push-to-talk capture is an execution workflow. Closing a window binds confirmation to the window captured when recording starts (or when the text request arrives), not whichever window the popup later focuses. It returns a token for explicit UI/CLI approval (`omarchy-voice confirm TOKEN`); never approve tokens automatically or from recognized speech.

## Install the native widget and shortcut

The widget lives in `plugin/` (not the repository root). Copy that folder, enable it, and put it on the bar. Do not use `omarchy plugin add` on this repository URL.

**F5** is the hold-to-talk binding on this machine (record-style keycap, no Super/Shift). F9 stays Voxtype dictation. Super+S is Toggle scratchpad. Super+V stays Universal paste. Super+Ctrl+V stays Clipboard manager. Super+; is restored. Super+Shift+V is not used because releasing Shift first often never fires `stop`. The widget dropdown can display a different preferred shortcut; applying it still requires editing `~/.config/hypr/bindings.lua`. Normal activation is hold-to-talk only; alias enrollment uses explicit in-panel record/finish controls and does not execute recognized speech.

On this machine the backend, service, bar widget, and F5 binding are installed from this checkout. Other machines should follow [docs/integration.md](docs/integration.md).

## Development and validation

```sh
uv sync --python 3.12 --extra test --extra stt
XDG_STATE_HOME="$(mktemp -d "${TMPDIR:?}/voice-tests.XXXXXX")" uv run --extra test --extra stt pytest -q
uv run --extra stt omarchy-voice run 'workspace two'
python3 integrations/validate.py
uv build
```

`integrations/validate.py` uses installed Omarchy/Quickshell types and needs the current Wayland session. It validates the manifest, Lua syntax, native panel compilation and UI model state/error/token behavior without installing the plugin. Standalone qmllint can report missing installed `QProcess::ExitStatus` metadata despite successful native compilation. The service unit cannot pass its executable-path check until the backend is installed at `~/.local/bin/omarchy-voice`.

### Verification status

- **189 automated tests passed** after integrating the branches, adding atomic saved-phrase updates, and retiring the three Spotify STT-mishearing defaults. They cover backend unit/security/daemon integration, routed phrase listing, reviewed alias storage/permissions/no-execution recording, app-scope process lifetime, desktop actions, OSD, and bounded STT settings writes.
- Native manifest/Lua/QML harness executed successfully against this machine's installed shell, including two simulated monitor instances receiving the same alias review; only the recording instance emits the reopen signal. This is a model regression, distinct from live popup placement verification.
- The backend with the app-scope fix, current-command catalog, and monitor-specific `VoiceModel.qml` change are installed locally. The user visually approved the **Current configured commands / New command** layout and previously reported that after recording on the right monitor and clicking **Finish recording**, review stayed on the right; after saving and applying a Spotify phrase, no voice-opened apps closed. The icon-row UI is installed after an Omarchy Shell reload but still needs a live click check. With user permission the voice service was restarted; it returned Ready, and dry-runs now route **open brave** to Brave, **open spotify** to Spotify, and reject **open and spotify**. This is not a new live microphone acceptance check.
- “Open the terminal” parses as `app.launch` for `terminal`; its dry-run produces `omarchy launch terminal`. Reinstall and restart the user service after updating the backend. The lifetime regression uses a harmless Python fixture, not a live terminal window.
- Actual Faster-Whisper `tiny.en` CPU transcription succeeded on the public whisper.cpp `samples/jfk.wav` recording; no mocked STT was used for that check.
- Real CLI dry-run for “workspace two” produced `hyprctl dispatch hl.dsp.focus({workspace="2"})` without running it; all doctor dependency checks passed in the development environment.
- **Not yet verified systematically:** live microphone → alias enrollment → spoken alias → real desktop action; installed widget popup/focus across monitors; physical F5 release ordering; CUDA; long-session stability and latency targets. Automated fixtures and initial user feedback are not substitutes for these acceptance checks.

## Missing / intentionally deferred

- Full measured live microphone/shortcut acceptance. The bar widget and F5 binding are installed on this machine; popup/focus across monitors and hold-to-talk release behavior still need a systematic check.
- In-panel permission/microphone configuration, model-download UI and graphical onboarding. Provider/model/device/language are now in Settings; remaining keys still live in `config.toml`.
- Additional production STT providers (see [Speech providers](#speech-providers)), streaming and persistent/shared model service (models currently run in isolated workers).
- Internationalized command grammars, wake word, always-listening, cloud STT, LLM/Hermes integration, arbitrary shell, power actions and provider marketplace.
- AUR/distribution packaging, config migrations, broad compatibility and performance benchmarks.

See the [original architecture proposal](docs/architecture.md) and [implementation decisions](docs/adr/0001-mvp-boundaries.md), including the [spoken-alias decision](docs/adr/0003-user-approved-app-aliases.md). The proposal describes future goals, not implemented features.

## Speech providers

v0.1 ships **one** production STT: local **faster-whisper**. Settings has a **Provider** dropdown plus capability dropdowns for that provider. There is no whisper.cpp, Voxtype, Parakeet, or cloud row.

| Setting | Current values | Notes |
| --- | --- | --- |
| Provider | `faster-whisper` | Only allowlisted name; anything else is rejected |
| Model | `tiny.en` (default), `base.en`, `small.en` | Larger models need `omarchy-voice download-model` first |
| Device | `cpu` (default); `cuda` if `/dev/nvidia0` exists | CPU uses `int8`; CUDA uses `float16` |
| Language | `en` | The command parser is English-only |

Hold F5 still records a WAV, then a **spawned worker** loads the model (`local_files_only=True`) and returns text to the deterministic parser. Voxtype (F9) stays a separate dictation app.

Panel writes go through `omarchy-voice settings stt <key> <value>` into `~/.config/omarchy-voice/config.toml`. The running daemon does **not** reload STT until **Apply STT** / `systemctl --user restart omarchy-voice.service`. CLI: `omarchy-voice settings show`.

### Adding another provider

Do not add a Settings row until that provider can actually transcribe. Concrete steps:

1. Implement the existing `STTProvider` contract in `src/omarchy_voice/providers.py`: `available()`, `capabilities()`, `transcribe(audio, language)` on a WAV file. Keep optional imports lazy.
2. Register the name on `STT_PROVIDERS` in `config.py`. Unknown `provider =` values must still fail closed.
3. Advertise Settings options from `stt_options()`: `providers` plus `capabilities[name]` arrays for that engine (`model` / `device` / `language`, or none). Empty arrays hide those dropdowns.
4. Route `IsolatedSTT` / `download_model` / `omarchy-voice providers` by `config.provider`. Add an optional extra in `pyproject.toml` instead of a required dependency.
5. Tests: unknown provider rejected; capability JSON matches the UI; a fake/unavailable provider is not listed as selectable.

Keep audio local unless the user explicitly opts into a networked engine. Do not merge Voxtype into this dropdown (F9 dictation stays independent). Do not send transcripts to an LLM for intent.

## Update / uninstall

After updating the checkout, reinstall the backend from its current source:

```sh
uv tool install --force --python 3.12 --from '.[stt]' omarchy-voice
# If installed as a service:
systemctl --user restart omarchy-voice.service
```

Follow the integration guide to replace the manually copied plugin/helper/service and remove optional bindings. `omarchy plugin update` does not update manual copies. Uninstall the backend using `uv tool uninstall omarchy-voice`; configuration and model caches are not silently removed.

## Documentation policy

README describes the **current** behavior, implementation status and installation/run commands. Every behavior change must update it, replacing stale instructions rather than appending contradictory historical guidance. Original design context belongs in the architecture proposal; decision rationale belongs in ADRs.

## Design and UX backlog

The initial **Application → Voice phrase** controls work in the panel, but this is a functional first pass, not the intended finished design. Priorities to discuss and prototype:

1. **Clearer setup flow:** the panel opens on the application grid. Clicking an app reveals **Voice commands**, with current routed built-in/configured phrases (or an empty state), then **New command** to reveal enrollment. The only app action is **Open application**; no command is invented for unconfigured apps. The separate **Desktop** catalog remains unchanged. Settings is reached from a button next to Start/Stop. Remaining polish: denser layout, keyboard navigation, and bringing the app detail into view on selection.
2. **Recording and review feedback:** show a bounded recording timer and unmistakable listening/transcribing/review states. Present the recognized phrase prominently with **Retry**, **Edit**, and **Save** paths; never execute a training utterance or imply that saving audio retrains the STT model.
3. **Voice phrase management:** saved app aliases render once as phrase → action rows instead of raw JSON. Remaining: inline edit/remove on each row, and a clear pending-vs-applied state. Preserve explicit restart/undo semantics and exact-match validation.
4. **App picker polish:** the Applications grid and app selection share the same trusted `apps` list, including a sanitized `Icon=` field. Remaining: empty/duplicate states, keyboard navigation in the popup, and layout/contrast checks on both monitors.
5. **Provider presentation:** Settings has a **Provider** dropdown. v0.1 lists only **faster-whisper**. Model, Device and Language appear from that provider’s capabilities (tiny.en / base.en / small.en, CPU, English). CUDA appears only when `/dev/nvidia0` exists or the current config is already cuda. Writes go through `omarchy-voice settings stt <key> <value>` into `config.toml`; the running daemon does not pick them up until **Apply STT**. Do not add whisper.cpp, Voxtype, or cloud rows until those providers exist.
6. **Future action design:** the app panel currently offers only **Open application**, without an action picker. Closing an app is not implemented; define an explicit target and nonvoice confirmation policy before offering it. Do not repurpose the existing focused-window close as silent app termination.

## Bugs
Intermittent local transcription failures are distinct from the observed Spotify phrase mishears. `doctor` checks the STT dependency but not model readiness; use `omarchy-voice logs` to diagnose a transcription failure. The new alias panel has initial positive user feedback, but Spotify launch after enrollment still needs a documented end-to-end check.

Fixed in the supplied service unit: **open terminal → `sudo` failed** with `The "no new privileges" flag is set`. The user service had `NoNewPrivileges=yes`, which the kernel inherits into every launched application. The flag was removed from `integrations/omarchy-voice.service`; see [ADR 0002](docs/adr/0002-launched-app-privileges.md). After updating, reinstall the unit and run `systemctl --user daemon-reload && systemctl --user restart omarchy-voice.service`. Also close **all** windows of a terminal opened before the fix and launch a fresh one: Ghostty uses a single-instance process, so new windows can reuse the old process and keep its inherited flag even after the voice service restarts. Save work first; closing the terminal running this session would end it. Verify the new terminal's `NoNewPrivs` is 0 via `/proc/$$/status` before trying `sudo`.
