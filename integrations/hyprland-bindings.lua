-- OPT-IN ONLY. Review your bindings before copying into ~/.config/hypr/bindings.lua.
-- Default F5 is unused on this Omarchy install and does not require Super/Shift,
-- so hold-to-talk release is reliable. F9 stays Voxtype dictation.
-- Super+V stays Universal paste. Super+Ctrl+V stays Clipboard manager.
-- Super+S stays Toggle scratchpad. Super+; is left alone.
-- o.bind passes its options to hl.bind; release=true is the installed API.
hl.unbind("F5")
o.bind("F5", "Voice: start push-to-talk", "omarchy-voice start")
o.bind("F5", "Voice: stop push-to-talk", "omarchy-voice stop", { release = true })
-- If a compositor misses the release, the backend recording limit bounds
-- capture; use the panel Cancel button.
