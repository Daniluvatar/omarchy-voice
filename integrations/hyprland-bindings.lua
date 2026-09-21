-- OPT-IN ONLY. Review your bindings before copying into ~/.config/hypr/bindings.lua.
-- Stock Super+V is Universal paste; this snippet REPLACES that shortcut.
-- It does not change F9, Super+Ctrl+X, or the installed voxtype service.
-- o.bind passes its options to hl.bind; release=true is the installed API.
hl.unbind("SUPER + V")
o.bind("SUPER + V", "Voice: start push-to-talk", "omarchy-voice start")
o.bind("SUPER + V", "Voice: stop push-to-talk", "omarchy-voice stop", { release = true })
-- Release V before Super. If a compositor misses the release, the backend's
-- maximum recording duration bounds capture; use the panel Cancel button.
