-- OPT-IN ONLY. Review your bindings before copying into ~/.config/hypr/bindings.lua.
-- Back up bindings.lua first and inspect F5 with:
--   omarchy menu keybindings --print | grep -i 'F5'
-- F5 is the default hold-to-talk key here and does not require Super/Shift,
-- so hold-to-talk release is reliable. Do not assume F5 is unused: inspect it
-- first; if it already has a binding you use, pick another chord. F9 stays
-- Voxtype dictation.
-- Super+V stays Universal paste. Super+Ctrl+V stays Clipboard manager.
-- Super+S stays Toggle scratchpad. Super+; is left alone.
-- o.bind passes its options to hl.bind; release=true is the installed API.
-- If F5 already has a binding you use, pick an unused chord and add a matching
-- press/release pair instead of replacing F5 (example commented out below).
hl.unbind("F5")
o.bind("F5", "Voice: start push-to-talk", "omarchy-voice start")
o.bind("F5", "Voice: stop push-to-talk", "omarchy-voice stop", { release = true })
-- o.bind("SUPER + SEMICOLON", "Voice: start push-to-talk", "omarchy-voice start")
-- o.bind("SUPER + SEMICOLON", "Voice: stop push-to-talk", "omarchy-voice stop", { release = true })
-- To restore an earlier F5 binding, remove this snippet and re-add the original
-- line(s) from the backup; if F5 was unbound before, removing it restores stock state.
-- If a compositor misses the release, the backend recording limit bounds
-- capture; use the panel Cancel button.
