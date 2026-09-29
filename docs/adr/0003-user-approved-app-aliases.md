# ADR 0003: User-approved spoken aliases in the native panel

Status: accepted for the local alias workflow.

## Context

Offline STT may render a proper name inconsistently: repeated attempts to say
“open Spotify” produced “open is putty high”. Treating arbitrary similar-sounding
words as app commands would weaken the deterministic action boundary. Keeping
recorded audio does not teach faster-whisper a new vocabulary.

## Decision

The native panel may record a bounded phrase using the existing local STT
worker in **alias review mode**. In that mode the backend returns the transcript
for review, deletes the temporary WAV and never parses or executes it as an
action. The panel offers a searchable installed-app dropdown, an action dropdown
(currently Open application only), and a record-or-type voice phrase dropdown.
The user explicitly chooses an installed app by exact desktop ID and approves a
text mapping. The CLI validates the phrase and installed app, then atomically
writes only the exact mapping to
`$XDG_CONFIG_HOME/omarchy-voice/aliases.json` (default `~/.config`). The
existing TOML and built-in aliases remain intact; user-approved JSON aliases
override duplicate TOML keys when the service restarts. The UI offers removal.

Recording is optional: users can type a stable phrase such as “music app”, or
review an STT mishearing such as “is putty high”. Each alias still goes through
normal app permissions and desktop-entry validation. No arbitrary shell, fuzzy
matching or voice-only approval is added. A restart is an explicit panel button,
not triggered by microphone input or saving the alias. The recording is not
stored; the reviewed transcript remains in local diagnostics under the existing
log policy.

## Amendment

A saved phrase must not retarget a command that already opens a different installed application. **open brave** and **open chromium** are separate app phrases. **open browser** is a role: with no saved phrase it runs `omarchy launch browser`, so a change of the OS default applies without editing voice configuration. Saving **open browser** pins only that phrase; removing it returns to the OS default.

## Limits

Only application launches can be aliased. Recognition errors unrelated to
app names (including intermittent STT failures) are not fixed by an alias.
The panel and real microphone workflow still require live acceptance testing;
QML compilation and injected-worker tests do not prove that the live UI works.
