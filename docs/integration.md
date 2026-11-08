# Desktop integration

Nothing in this repository installs itself. These steps are opt-in. They do not modify `/usr/share/omarchy`, Voxtype, or F9.

The widget id is `local.omarchy-voice`. `omarchy.*` is reserved for first-party plugins. The install manifest is at the repository root; its entry point is `plugin/VoicePanel.qml`. Install from the public git URL with `omarchy plugin add`, which validates the cloned tree, records `clonedFrom`, and makes `omarchy plugin update` work. A copied plugin is not tracked by updates.

Install the backend first. See the repository README. The unit expects `~/.local/bin/omarchy-voice` on `PATH`.

```sh
command -v omarchy-voice
omarchy-voice doctor
```

## Install

Install the backend first. The installer validates a clean checkout with `omarchy plugin validate .`; do not run that root validation after creating the development `.venv`, because `.venv` contains symlinks that are not part of an installation.

```sh
omarchy plugin add https://github.com/Daniluvatar/omarchy-voice.git --enable
PLUGIN_DIR="$HOME/.config/omarchy/plugins/local.omarchy-voice"
install -Dm755 "$PLUGIN_DIR/integrations/omarchy-voice-edit-config" "$HOME/.local/bin/omarchy-voice-edit-config"
install -Dm644 "$PLUGIN_DIR/integrations/omarchy-voice.service" "$HOME/.config/systemd/user/omarchy-voice.service"
systemctl --user daemon-reload
systemctl --user enable --now omarchy-voice.service
omarchy bar put local.omarchy-voice --section right --index 0
```

The plugin scripts use `$HOME/.config/omarchy/plugins`. If that plugin is already installed, use the update steps instead of adding it again. If the backend binary is elsewhere, edit the installed unit’s `ExecStart` before starting it. Do not run `omarchy-voice serve` beside this unit.

The unit follows the graphical session. If actions cannot connect, inspect `systemctl --user show-environment` for `WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE`. Do not hard-code another session’s values.

The widget polls only while the bar has loaded it. Disabling the widget does not cancel a capture. Use the panel or `omarchy-voice cancel`.

## Shortcut

F5 is the default hold-to-talk key used by this integration. Do not assume it is unused: the supplied snippet deliberately unbinds F5, so inspect the existing binding first. F9 stays Voxtype. Super+V, Super+Ctrl+V, and Super+S stay as they are.

Inspect current bindings and back up the file before editing:

```sh
omarchy menu keybindings --print | grep -i 'F5'
cp ~/.config/hypr/bindings.lua ~/.config/hypr/bindings.lua.bak-$(date +%Y%m%d)
```

If F5 is already bound to something you use, choose an unused chord instead of replacing it, or accept the replacement deliberately. Review `integrations/hyprland-bindings.lua`, copy its three lines into `~/.config/hypr/bindings.lua`, then:

```sh
hyprctl reload
hyprctl configerrors
```

The snippet deliberately unbinds F5. To restore the original binding, remove the snippet, re-add the original F5 line(s) from the backup, reload, and check `hyprctl configerrors`. If F5 had no prior binding, removing the snippet restores the stock state.

The widget shortcut setting does not write that file. To use a different chord, add a reviewed press/release pair for it with the same `omarchy-voice start` and `omarchy-voice stop` commands. Do not apply the Lua snippet to an older `.conf` Hyprland configuration without checking that version’s API.

## Update

```sh
omarchy-voice cancel
omarchy plugin update local.omarchy-voice
PLUGIN_DIR="$HOME/.config/omarchy/plugins/local.omarchy-voice"
install -Dm755 "$PLUGIN_DIR/integrations/omarchy-voice-edit-config" "$HOME/.local/bin/omarchy-voice-edit-config"
install -Dm644 "$PLUGIN_DIR/integrations/omarchy-voice.service" "$HOME/.config/systemd/user/omarchy-voice.service"
systemctl --user daemon-reload
systemctl --user restart omarchy-voice.service
omarchy plugin enable local.omarchy-voice
omarchy bar put local.omarchy-voice --section right --index 0
```

`omarchy plugin update` fetches the recorded `clonedFrom` URL, validates the new tree, and fast-forwards only when the checkout is clean. Do not replace the installed directory by hand. If the bar still shows the previous widget, `omarchy restart shell`.

## Uninstall

1. `omarchy-voice cancel`
2. `systemctl --user disable --now omarchy-voice.service`
3. `omarchy plugin remove local.omarchy-voice` (this removes the git checkout and unloads it; do not `rm` the directory by hand)
4. Remove `~/.config/systemd/user/omarchy-voice.service` and `~/.local/bin/omarchy-voice-edit-config`, then `systemctl --user daemon-reload`
5. Remove the F5 unbind and press/release binds from `~/.config/hypr/bindings.lua`, then reload and check Hyprland. Restore any earlier F5 binding from the backup instead of leaving F5 unbound.
6. `uv tool uninstall omarchy-voice` only if the backend should be removed

Leave `config.toml`, `voice_commands.json`, and the model cache unless you intend to delete them. Do not change F9, Voxtype, or packaged Omarchy files.

## Check without installing

```sh
python3 integrations/validate.py
```

That compiles the panel against the installed shell types and runs the panel harnesses. It needs Wayland. It does not install the plugin, open the microphone, or run a desktop action.
