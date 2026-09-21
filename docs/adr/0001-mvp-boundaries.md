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

## Consequences

Same-user processes and installed provider code remain trusted. This is not a multi-user authentication service. Microphone control and action execution are opt-in through explicit startup/installation. Hardware acceptance is separate from automated tests.
