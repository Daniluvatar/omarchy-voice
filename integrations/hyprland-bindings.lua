-- OPT-IN ONLY. Review your bindings before copying into ~/.config/hypr/bindings.lua.
-- Default Super+; is unused on stock Omarchy and does not require Shift, so
-- hold-to-talk release is reliable. Super+V stays Universal paste.
-- Super+Ctrl+V stays Clipboard manager. Super+S stays Toggle scratchpad.
-- Super+Shift+V is not used: releasing Shift first often never fires stop.
-- o.bind passes its options to hl.bind; release=true is the installed API.
hl.unbind("SUPER + SEMICOLON")
o.bind("SUPER + SEMICOLON", "Voice: start push-to-talk", "omarchy-voice start")
o.bind("SUPER + SEMICOLON", "Voice: stop push-to-talk", "omarchy-voice stop", { release = true })
-- If a compositor misses the release, the backend recording limit bounds
-- capture; use the panel Cancel button.
