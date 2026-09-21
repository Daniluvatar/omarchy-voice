-- OPT-IN ONLY. Review your bindings before copying into ~/.config/hypr/bindings.lua.
-- Default Super+Shift+V is unused on stock Omarchy.
-- Super+V stays Universal paste. Super+Ctrl+V stays Clipboard manager.
-- Super+S stays Toggle scratchpad. F9 / Super+Ctrl+X / voxtype are left alone.
-- o.bind passes its options to hl.bind; release=true is the installed API.
hl.unbind("SUPER + SHIFT + V")
o.bind("SUPER + SHIFT + V", "Voice: start push-to-talk", "omarchy-voice start")
o.bind("SUPER + SHIFT + V", "Voice: stop push-to-talk", "omarchy-voice stop", { release = true })
-- Release V before Super/Shift. If a compositor misses the release, the
-- backend's maximum recording duration bounds capture; use the panel Cancel button.
