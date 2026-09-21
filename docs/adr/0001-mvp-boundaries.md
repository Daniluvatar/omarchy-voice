# ADR 0001: Local-first architectural MVP

Status: accepted for v0.1 implementation.

## Decisions

- Python core packaged separately from Quickshell UI. UI invokes an argv-only CLI; the CLI communicates with a local, permission-restricted Unix socket.
- PipeWire capture is independent from speech recognition. Temporary normalized audio is deleted; transcription and recording history are not retained by default.
- Faster-Whisper is optional at package install and required for the reference speech workflow. Offline inference follows explicit model preparation; model acquisition requires network access but speech does not leave the device.
- Built-in English deterministic commands only. Unsupported and malformed requests fail closed.
- A restricted action router validates targets and permission settings. No shutdown/reboot/shell action. Closing the active window requires nonvoice confirmation.
- Installed desktop entries supply app discovery. They are trusted local executable configuration, not a sandbox for hostile installed applications.
- Fake STT is test-only, demonstrating interchangeable providers without exposing a production command-injection shortcut.
- Keep existing Voxtype/F9 dictation untouched. `voxtype transcribe --help` confirms an audio-file transcription command exists on the inspected installation; output semantics and shared model lifecycle remain unvalidated and are not v0.1 dependencies.
- Native Omarchy plugin compatibility is checked against the installed shell. Never edit the packaged source to integrate this project.
- Spoken "open terminal" uses the fixed argv `omarchy launch terminal` unless a `terminal` desktop alias is configured. This avoids a hard-coded Alacritty desktop ID that is not present on stock Omarchy.
- v0.1 activation is hold-to-talk only. The widget can display a preferred shortcut, but Hyprland still owns the actual binding. Super+V (paste), Super+Ctrl+V (clipboard manager), Super+S (scratchpad), and F9 (Voxtype) stay occupied. Super+Shift+V is a poor hold chord because releasing Shift first often never fires stop; the current default is unused F5.

## Consequences

Same-user processes and installed provider code remain trusted. This is not a multi-user authentication service. Microphone control and action execution are opt-in through explicit startup/installation. Hardware acceptance is separate from automated tests.
