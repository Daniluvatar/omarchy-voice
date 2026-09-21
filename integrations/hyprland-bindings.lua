-- OPT-IN ONLY. Review your bindings before copying into ~/.config/hypr/bindings.lua.
-- Stock Super+S is Toggle scratchpad; this snippet REPLACES that shortcut.
-- Super+V (Universal paste), F9, Super+Ctrl+X, and voxtype are left alone.
-- o.bind passes its options to hl.bind; release=true is the installed API.
hl.unbind("SUPER + S")
o.bind("SUPER + S", "Voice: start push-to-talk", "omarchy-voice start")
o.bind("SUPER + S", "Voice: stop push-to-talk", "omarchy-voice stop", { release = true })
-- Release S before Super. If a compositor misses the release, the backend's
-- maximum recording duration bounds capture; use the panel Cancel button.
