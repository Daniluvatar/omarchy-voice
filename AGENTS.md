# Development rules

- Keep README.md an accurate description of the current implementation, supported commands, installation and run instructions. Update it with every behavior/configuration/integration change; replace stale guidance rather than appending contradictory instructions.
- Track implementation versus verification separately. Never mark live microphone/STT/desktop/UI behavior verified from mocks alone.
- Preserve docs/architecture.md as the original proposal. Document deviations in docs/adr/.
- Keep transcription untrusted. No arbitrary shell execution, fuzzy dangerous-action matching, or voice-only confirmation.
- Never alter /usr/share/omarchy or existing dictation. Installation and keybinding changes must be explicit and reversible.
- Run unit, security and integration tests before commits. Do not execute close/lock or other disruptive desktop actions while testing without explicit consent.
- Use repository-local Git identity Daniluvatar <daniluvatar@gmail.com>; verify authenticated GitHub identity is Daniluvatar before publishing.
