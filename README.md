# Omarchy Voice

Local push-to-talk voice commands for Omarchy. Speech is transcribed on this machine. A Python service plans and runs a fixed set of desktop actions. An Omarchy bar widget shows status, confirmation, and saved phrases.

Hold the shortcut, speak, release. The default binding is **F5**. F9 stays Voxtype dictation and is not part of this plugin.

```text
Hold F5 → PipeWire → local faster-whisper → exact command
                                              ↓
                         permission check → registered desktop action
```

This is a v0.1 implementation, not a finished public product. The [architecture proposal](docs/architecture.md) describes goals that are not implemented. Decisions that differ from that proposal are in [docs/adr/](docs/adr/).

## Use

1. Hold **F5**, speak one command, release.
2. The bar widget follows the service: listening, transcribing, running, confirm, or error.
3. **Close window** does not run until you confirm it in the panel. Speech cannot approve it.
4. Open the widget to enroll a phrase, inspect commands, or change speech settings.

The panel has two catalogs:

- **Applications.** Installed apps. An app is **Configured** when at least one voice command can currently route to it: a built-in phrase from the app catalog, or a saved phrase. Configured apps are listed first, alphabetically, then the remaining apps, alphabetically. Click an app to see its commands or add a phrase. **Open application** is the only app action, and the panel does not launch it.
- **Desktop.** Window, workspace, and system phrases the router actually plans. These are not Super+K chords.

Saving a phrase does not activate it. Click **Apply saved phrases**. That restarts the user service and checks that the running daemon reports the saved configuration. Speech settings work the same way: **Apply STT** restarts the service. Until then, the panel is showing saved configuration, not what the daemon has loaded.

After a successful spoken action that has a Super+K chord, the Omarchy OSD can show that chord only. **Show keybinding** in Settings turns the overlay off. Actions without a chord, and relative workspace moves, show nothing.

## Spoken commands

| Say | Result |
| --- | --- |
| Open / launch / start `<application>` | Launch that installed application |
| Open terminal | `omarchy launch terminal`, unless a `terminal` phrase is saved |
| Open browser | `omarchy launch browser` (the OS default browser) |
| Open Brave / Open Chromium | Those apps only. The names are not synonyms |
| Close window | Ask for confirmation, then close the window focused when recording started |
| Move this window left / right | Move the focused window to that monitor |
| Move this window to the other screen | Move the focused window to the other monitor |
| Workspace one … ten | Switch to workspace 1–10 |
| Switch / move to workspace four | Move the focused window to workspace 4 |
| Move window to the left / right workspace | Move the focused window one workspace |
| Volume up / Volume down | Change output volume |
| Mute | Toggle output mute |
| Lock computer | Lock the desktop |

Matching is exact after light normalization: a sentence-ending period, a comma after “open”, and a few workspace mishears (`water space`, `for` as four). Unknown or ambiguous speech does nothing. Numbered window labels are rejected. Closing an application is not implemented.

**Move … left/right** without `workspace` is a monitor move. **… left/right workspace** is a workspace move. **Open the terminal**, **open term**, and **open ghostty** also run `omarchy launch terminal` unless you save a `terminal` phrase. Window moves use the window focused when you press F5.

## Install the backend

Requires a graphical Omarchy session, a systemd user manager, PipeWire (`pw-record`), `wpctl`, `gio`, `hyprctl`, and `uv`. Python 3.12 is the tested runtime. `uv` provides it; system Python is not modified.

```sh
git clone https://github.com/Daniluvatar/omarchy-voice.git
cd omarchy-voice
uv tool install --python 3.12 --from '.[stt]' omarchy-voice
omarchy-voice doctor
omarchy-voice download-model
```

`~/.local/bin` must be on `PATH`. The repository is private. `download-model` needs network once. After that, transcription uses the local Hugging Face cache and does not send audio off the machine. The default model is `tiny.en`.

The `stt` extra pins PyAV below 19. faster-whisper 1.x still passes `metadata_errors` to `av.open()`, which PyAV 19 removed. If a tool environment was created before that pin, reinstall with `uv tool install --force --python 3.12 --from '.[stt]' omarchy-voice` and restart the service.

`doctor` checks that the required programs and the STT package are present. It does not prove the model can transcribe.

## Install the widget

The widget is the `plugin/` directory, id `local.omarchy-voice`. Do not run `omarchy plugin add` on this repository: that command expects a manifest at the repository root. Do not edit `/usr/share/omarchy`. A manual copy is not updated by `omarchy plugin update`.

From the repository root, after the backend is on `PATH`:

```sh
omarchy plugin validate ./plugin
test ! -e "$HOME/.config/omarchy/plugins/local.omarchy-voice" && \
  cp -R ./plugin "$HOME/.config/omarchy/plugins/local.omarchy-voice"
install -Dm755 integrations/omarchy-voice-edit-config "$HOME/.local/bin/omarchy-voice-edit-config"
install -Dm644 integrations/omarchy-voice.service "$HOME/.config/systemd/user/omarchy-voice.service"
systemctl --user daemon-reload
systemctl --user enable --now omarchy-voice.service
omarchy plugin enable local.omarchy-voice
omarchy bar put local.omarchy-voice --section right --index 0
```

If that plugin directory already exists, use [Update and uninstall](#update-and-uninstall). Do not merge an old copy with a new one. If the bar does not pick up a replaced widget, run `omarchy restart shell`.

Do not run `omarchy-voice serve` while the user service is active. The unit expects `~/.local/bin/omarchy-voice`. If desktop actions cannot see the session, check `systemctl --user show-environment` for `WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE`. Do not hard-code another session’s values.

The widget polls only while the bar loads it. Hiding the widget does not stop a capture. Cancel from the panel or with `omarchy-voice cancel`. The reversible widget steps are also in [docs/integration.md](docs/integration.md).

## Shortcut

F5 is opt-in. Review `integrations/hyprland-bindings.lua`, then copy the `hl.unbind` and the two `o.bind` lines into `~/.config/hypr/bindings.lua`. Press starts capture. Release stops it. Then:

```sh
hyprctl reload
hyprctl configerrors
```

The widget’s shortcut dropdown changes the label only. It does not rewrite Hyprland. Leave F9, Super+V, Super+Ctrl+V, and Super+S alone. Do not hold F5 and F9 together. If a release is missed, capture stops at the configured limit; use Cancel.

## Configuration

Optional file: `~/.config/omarchy-voice/config.toml` (`XDG_CONFIG_HOME` is respected). Unknown keys and unknown action IDs are rejected.

```sh
mkdir -p ~/.config/omarchy-voice
test -e ~/.config/omarchy-voice/config.toml || cp examples/config.toml ~/.config/omarchy-voice/config.toml
```

Defaults allow the supported actions. Window closing still requires confirmation. To deny execution while setting up:

```toml
[permissions]
allow = []
```

Allowed action IDs: `app.launch`, `window.close`, `window.move_monitor`, `window.move_workspace`, `workspace.switch`, `audio.volume`, `audio.mute`, `system.lock`.

| Setting | Values |
| --- | --- |
| Provider | `faster-whisper` only |
| Model | `tiny.en` (default), `base.en`, `small.en` |
| Device | `cpu` (default). `cuda` only if `/dev/nvidia0` exists or is already configured |
| Language | `en` |
| Capture limit | 15 seconds |
| STT timeout | 60 seconds |
| Confirmation expiry | 15 seconds |

Panel writes use `omarchy-voice settings stt <key> <value>`. Also: `omarchy-voice settings show` and `omarchy-voice settings keybind-osd on|off`.

Saved phrases live in `~/.config/omarchy-voice/voice_commands.json`. A pre-rename `aliases.json` is migrated once and is not applied again. That file overrides a duplicate `[applications.voice_commands]` entry in TOML. Example desktop IDs in `examples/config.toml` are not a promise that those apps are installed. The CLI accepts an application name or a desktop id.

A phrase that already opens another specific application is rejected. **open browser** may be saved once, which pins that role; removing it returns the phrase to the OS default. **open brave** and **open chromium** cannot be moved onto each other. Built-in and TOML phrases are read-only in the panel.

## CLI

`run` and `transcribe` are dry runs unless `--execute` is passed. `--execute` and `start` require the daemon. `start` uses the microphone and runs a permitted command.

```sh
omarchy-voice parse 'workspace two'
omarchy-voice run 'workspace two'
omarchy-voice run 'open terminal'
omarchy-voice serve
omarchy-voice start          # microphone; executes
omarchy-voice stop           # end capture and transcribe; does not stop the daemon
omarchy-voice cancel
omarchy-voice status
omarchy-voice logs
omarchy-voice confirm TOKEN  # close-window approval; never from speech
omarchy-voice apps
omarchy-voice providers
omarchy-voice voice-command list
omarchy-voice voice-command set 'music app' Spotify
omarchy-voice voice-command update 'music app' 'favorite music' Spotify
omarchy-voice voice-command remove 'music app'
omarchy-voice transcribe /absolute/path/command.wav
omarchy-voice run 'workspace two' --execute
```

`alias` and `start-alias` are compatibility names for `voice-command` and `start-voice-command`. File transcription accepts a bounded PCM WAV. Recognized speech that is not a supported command returns an error and runs nothing.

Diagnostic lines, including the transcript, are appended to `~/.local/state/omarchy-voice/voice.log`. Panel errors stay short and do not include paths or Python tracebacks. Use `omarchy-voice logs` for the recorded exception.

## Implementation

- Capture is a bounded PipeWire recording. The WAV is deleted. Enrollment does not keep training audio and does not execute the heard text.
- Transcription is local faster-whisper in a separate worker (`local_files_only` after download). CPU uses `int8`. CUDA uses `float16`.
- The parser is deterministic English. It never turns a transcript into a shell command. Shutdown and reboot are not actions.
- Application launch uses validated argv, detached from the service through `systemd-run --user --scope`. If the user manager cannot create that scope, the launch fails. A launched app is not a child of the voice service, so restarting the service does not close it. Other desktop actions time out after 10 seconds. See [ADR 0004](docs/adr/0004-app-launch-scopes.md).
- The supplied user unit does not set `NoNewPrivileges`. That flag was inherited by launched apps and broke `sudo` inside them. See [ADR 0002](docs/adr/0002-launched-app-privileges.md). A terminal process started before that fix can keep the old flag until its process exits.
- The Applications grid comes from `omarchy-voice apps` and the saved-phrase list. No application name is hard-coded. If either source is still missing when the panel opens, it retries that source every 2 seconds, at most 30 times, and keeps the last good list on failure.
- **Apply saved phrases** probes `omarchy-voice status` and compares `voice_commands_revision` with the revision last reported by `apps`. The revision is a digest of the mapping, not the phrases. A mismatch, a timeout, or a failed restart leaves the change pending.

## Update and uninstall

Backend:

```sh
uv tool install --force --python 3.12 --from '.[stt]' omarchy-voice
systemctl --user restart omarchy-voice.service
```

Widget: `omarchy-voice cancel`, then `omarchy plugin disable local.omarchy-voice`. Replace only `~/.config/omarchy/plugins/local.omarchy-voice` with a new copy of `plugin/`. Validate, enable, and `omarchy bar put` again. Reinstall the helper and unit if those files changed, then `systemctl --user daemon-reload` and restart the service. Run `omarchy restart shell` if the bar keeps the previous widget.

Uninstall:

1. `omarchy-voice cancel`
2. `systemctl --user disable --now omarchy-voice.service`
3. `omarchy plugin disable local.omarchy-voice`
4. Remove `~/.config/omarchy/plugins/local.omarchy-voice` after checking the path
5. Remove `~/.config/systemd/user/omarchy-voice.service` and `~/.local/bin/omarchy-voice-edit-config`, then `systemctl --user daemon-reload`
6. Remove the F5 lines from `~/.config/hypr/bindings.lua`, then `hyprctl reload` and `hyprctl configerrors`
7. `uv tool uninstall omarchy-voice` if the tool should go too

Do not delete `config.toml`, `voice_commands.json`, or the model cache unless that is intentional. Do not change F9, Voxtype, or anything under `/usr/share/omarchy`.

## Development

```sh
uv sync --python 3.12 --extra test --extra stt
uv run --extra test --extra stt pytest -q
python3 integrations/validate.py
```

`integrations/validate.py` needs the installed Omarchy shell and a Wayland session. It does not install the plugin, start the microphone, or run a desktop action.
