# Desktop integration

Nothing in this repository installs itself. These steps are opt-in. They do not modify `/usr/share/omarchy`, Voxtype, or F9.

The widget id is `local.omarchy-voice`. `omarchy.*` is reserved for first-party plugins. The manifest is `plugin/manifest.json`, not the repository root, so `omarchy plugin add` does not apply. A copied plugin is not tracked by `omarchy plugin update`.

Install the backend first. See the repository README. The unit expects `~/.local/bin/omarchy-voice` on `PATH`.

```sh
command -v omarchy-voice
omarchy-voice doctor
```

## Install

Run from the repository root. Stop if the plugin directory already exists; replace it with the update steps instead of merging trees.

```sh
omarchy plugin validate ./plugin
mkdir -p "$HOME/.config/omarchy/plugins"
test ! -e "$HOME/.config/omarchy/plugins/local.omarchy-voice" && \
  cp -R ./plugin "$HOME/.config/omarchy/plugins/local.omarchy-voice"
install -Dm755 integrations/omarchy-voice-edit-config "$HOME/.local/bin/omarchy-voice-edit-config"
install -Dm644 integrations/omarchy-voice.service "$HOME/.config/systemd/user/omarchy-voice.service"
systemctl --user daemon-reload
systemctl --user enable --now omarchy-voice.service
omarchy plugin enable local.omarchy-voice
omarchy bar put local.omarchy-voice --section right --index 0
```

Substitute `$XDG_CONFIG_HOME` when it is not `~/.config`. If the backend binary is elsewhere, edit the copied unit’s `ExecStart` before starting it. Do not run `omarchy-voice serve` beside this unit.

The unit follows the graphical session. If actions cannot connect, inspect `systemctl --user show-environment` for `WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE`. Do not hard-code another session’s values.

The widget polls only while the bar has loaded it. Disabling the widget does not cancel a capture. Use the panel or `omarchy-voice cancel`.

## Shortcut

F5 is unused on a stock Omarchy install and is the hold-to-talk key this integration uses. F9 stays Voxtype. Super+V, Super+Ctrl+V, and Super+S stay as they are.

Inspect current bindings with `omarchy menu keybindings --print`. Review `integrations/hyprland-bindings.lua`, copy its three lines into `~/.config/hypr/bindings.lua`, then:

```sh
hyprctl reload
hyprctl configerrors
```

The widget shortcut setting does not write that file. Do not apply the Lua snippet to an older `.conf` Hyprland configuration without checking that version’s API.

## Update

```sh
omarchy-voice cancel
omarchy plugin disable local.omarchy-voice
```

Back up `~/.config/omarchy/plugins/local.omarchy-voice` outside the plugin directory, replace it with a fresh `plugin/` copy, validate, enable, and put it on the bar again. Reinstall the helper and unit when those files changed:

```sh
install -Dm755 integrations/omarchy-voice-edit-config "$HOME/.local/bin/omarchy-voice-edit-config"
install -Dm644 integrations/omarchy-voice.service "$HOME/.config/systemd/user/omarchy-voice.service"
systemctl --user daemon-reload
systemctl --user restart omarchy-voice.service
```

If the bar still shows the previous widget, `omarchy restart shell`.

## Uninstall

1. `omarchy-voice cancel`
2. `systemctl --user disable --now omarchy-voice.service`
3. `omarchy plugin disable local.omarchy-voice`
4. Remove `~/.config/omarchy/plugins/local.omarchy-voice` after checking the path
5. Remove `~/.config/systemd/user/omarchy-voice.service` and `~/.local/bin/omarchy-voice-edit-config`, then `systemctl --user daemon-reload`
6. Remove the F5 unbind and press/release binds from `~/.config/hypr/bindings.lua`, then reload and check Hyprland
7. `uv tool uninstall omarchy-voice` only if the backend should be removed

Leave `config.toml`, `voice_commands.json`, and the model cache unless you intend to delete them. Do not change F9, Voxtype, or packaged Omarchy files.

## Check without installing

```sh
python3 integrations/validate.py
```

That compiles the panel against the installed shell types and runs the panel harnesses. It needs Wayland. It does not install the plugin, open the microphone, or run a desktop action.
