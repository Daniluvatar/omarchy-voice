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
- Strict action/parameter validation, action permissions, expiring single-use nonvoice confirmation for window closing. No arbitrary shell, shutdown or reboot action.
- Unix-socket daemon with owner-only runtime permissions, bounded requests, duplicate-instance protection, cancellation and killable transcription worker.
- JSON CLI, dry-run command planning, diagnostics, model download, and `omarchy-voice logs` for the local diagnostic file.
- Native Omarchy bar widget/panel: state, controls, local-processing label, provider metadata, confirmation, and in-panel shortcut buttons. Settings do not rewrite Hyprland by themselves.
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

Ordinary single sentence-ending punctuation from STT is accepted. Unknown/ambiguous commands fail safely. Spoken **open terminal**, **open the terminal**, **open term**, **open termina**, **open terminator**, and **open ghostty** run `omarchy launch terminal` unless you configure a `terminal` desktop alias. Spoken **open browser** / **open brave** / **open brave browser** / **open chromium** map to Brave. Observed STT mishears **open a Spotify**, **open and Spotify**, and **open is Spotify** map only to the configured Spotify app. A comma after Open (`Open, brave.`) is ignored. Window moves accept a small set of natural phrases (`move this window to the left`, `move it to the other screen`, `switch to workspace four`, `move window to the left workspace`) and still use the window focused when you press F5. **Move … left/right** without `workspace` is a monitor move; **… left/right workspace** is a workspace move. Common STT mishears such as **water space** / **world space** and **for** / **forward** for four are normalized. Numbered window labels and app names are rejected. `app.close` is not implemented: only closing a window is supported. Volume directions use the shared `audio.volume` action with validated parameters, rather than separate action IDs in the proposal.

Application launches use validated argv without a shell, detached standard streams and a new process session. The backend watches the launcher for up to 250 ms: missing executables and immediate nonzero exits fail; a still-running launcher is accepted and reaped asynchronously when it exits, without a lifetime timeout or termination. Acceptance is not proof that a window appeared; failures after the startup window are not reported to the UI. This is process-session isolation, not escape from a systemd service cgroup: service shutdown can still affect children that have not been handed off to an application scope. Other desktop actions retain their 10-second command timeout.

## Install backend

Requirements: Linux graphical session with Omarchy/Hyprland, PipeWire `pw-record`, `wpctl`, `gio`, and `uv`. Python **3.12 is the tested runtime**; `uv` manages it without modifying system Python. CUDA is optional and untested. The native frontend targets the installed Omarchy 4.0.4-1 shell and Hyprland 0.56.2 Lua API, not older `.conf` configurations.

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

Allowed action IDs: `app.launch`, `window.close`, `window.move_monitor`, `window.move_workspace`, `workspace.switch`, `audio.volume`, `audio.mute`, `system.lock`. Unknown settings and action IDs are rejected. App aliases must match actual installed desktop IDs; the example IDs are not a promise that those apps are installed. Edit `[applications.aliases]` to match your installation. Default capture limit is 15 seconds, STT timeout 60 seconds, confirmation expiry 15 seconds. Configuration changes require restarting the daemon. `--config PATH` is a global option **before** the subcommand.

## Run without installing the desktop integration

First inspect commands without changing the desktop:

```sh
omarchy-voice parse 'workspace two'
omarchy-voice run 'workspace two'             # Dry run: prints validated argv
omarchy-voice run 'open terminal'             # Dry run: omarchy launch terminal
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

**F5** is the hold-to-talk binding on this machine (record-style keycap, no Super/Shift). F9 stays Voxtype dictation. Super+S is Toggle scratchpad. Super+V stays Universal paste. Super+Ctrl+V stays Clipboard manager. Super+; is restored. Super+Shift+V is not used because releasing Shift first often never fires `stop`. The widget dropdown can display a different preferred shortcut; applying it still requires editing `~/.config/hypr/bindings.lua`. Activation is hold-to-talk only.

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

- **173 automated tests passed**, covering backend unit/security/daemon integration, STT punctuation, default-terminal launch, narrow Spotify mishear aliases, local diagnostic logging, and focused-window monitor/workspace moves. Launch regressions include immediate failure detection, injected runners, permissions, narrow terminal-article parsing, and a harmless real subprocess that survives beyond 10 seconds and is reaped after exit.
- Native manifest/Lua/QML harness executed successfully against this machine's installed shell.
- “Open the terminal” parses as `app.launch` for `terminal`; its dry-run produces `omarchy launch terminal`. Reinstall and restart the user service after updating the backend. The lifetime regression uses a harmless Python fixture, not a live terminal window.
- Actual Faster-Whisper `tiny.en` CPU transcription succeeded on the public whisper.cpp `samples/jfk.wav` recording; no mocked STT was used for that check.
- Real CLI dry-run for “workspace two” produced `hyprctl dispatch hl.dsp.focus({workspace="2"})` without running it; all doctor dependency checks passed in the development environment.
- **Not yet verified:** live microphone → spoken supported command → real desktop action; installed widget popup/focus across monitors; physical F5 release ordering; CUDA; long-session stability and latency targets. Automated fixtures are not substitutes for these acceptance checks.

## Missing / intentionally deferred

- Full live microphone/shortcut acceptance. The bar widget and F5 binding are installed on this machine; popup/focus and hold-to-talk still need a live check.
- In-panel editable provider/permission/microphone configuration, model-download UI and graphical onboarding.
- Additional production STT providers, streaming and persistent/shared model service (models currently run in isolated workers).
- Internationalized command grammars, wake word, always-listening, cloud STT, LLM/Hermes integration, arbitrary shell, power actions and provider marketplace.
- AUR/distribution packaging, config migrations, broad compatibility and performance benchmarks.

See the [original architecture proposal](docs/architecture.md) and [implementation decisions](docs/adr/0001-mvp-boundaries.md). The proposal describes future goals, not implemented features.

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

## TechDebt
Dropdown provider
Dropdown app > action > recording

## Bugs
Intermittent local transcription failures are distinct from the observed Spotify phrase mishears. `doctor` checks the STT dependency but not model readiness; use `omarchy-voice logs` to diagnose a transcription failure. Spotify launch after live microphone transcription still requires a fresh end-to-end check.

Fixed in the supplied service unit: **open terminal → `sudo` failed** with `The "no new privileges" flag is set`. The user service had `NoNewPrivileges=yes`, which the kernel inherits into every launched application. The flag was removed from `integrations/omarchy-voice.service`; see [ADR 0002](docs/adr/0002-launched-app-privileges.md). After updating, reinstall the unit and run `systemctl --user daemon-reload && systemctl --user restart omarchy-voice.service`. Also close **all** windows of a terminal opened before the fix and launch a fresh one: Ghostty uses a single-instance process, so new windows can reuse the old process and keep its inherited flag even after the voice service restarts. Save work first; closing the terminal running this session would end it. Verify the new terminal's `NoNewPrivs` is 0 via `/proc/$$/status` before trying `sudo`.
