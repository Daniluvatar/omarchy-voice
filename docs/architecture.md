# Omarchy Voice --- Proposed Architecture and MVP Roadmap

**Status:** Initial architecture proposal\
**Target:** v0.1 MVP\
**Project goal:** Build an extensible, local-first voice-control
framework for Omarchy with interchangeable speech-to-text providers,
deterministic command interpretation, and a restricted action API.

------------------------------------------------------------------------

## 1. Vision

Omarchy Voice should not be tied to a single speech-recognition engine
or AI provider.

The project should provide a stable voice-control layer where users can
choose how speech is processed while Omarchy Voice remains responsible
for interpreting commands safely and executing supported desktop
actions.

The initial use case is intentionally simple:

``` text
Super + V
    ↓
Microphone
    ↓
Speech-to-Text
    ↓
"Open Brave"
    ↓
Intent Engine
    ↓
app.launch("brave")
    ↓
Action Router
    ↓
Brave opens
```

The architecture, however, should allow future implementations such as:

``` text
Speech Recognition
├── Faster-Whisper
├── whisper.cpp
├── Voxtype integration
├── Parakeet
├── Cloud STT
└── Custom provider

Intent Processing
├── Built-in deterministic commands
├── Local LLM
├── Hermes
├── Remote AI provider
└── Custom provider

Actions
├── Applications
├── Windows
├── Workspaces
├── Audio
├── System
├── Media
├── Smart home
└── Extensible third-party actions
```

The project should remain useful without an LLM or Internet connection.

------------------------------------------------------------------------

## 2. Design Principles

### 2.1 Local-first

The default/reference implementation should work entirely on the user's
machine.

Cloud providers may be supported later, but the UI must make it clear
when microphone audio or transcription data can leave the device.

### 2.2 Provider-agnostic

The Omarchy plugin must not depend directly on Faster-Whisper, Voxtype,
OpenAI, or another specific engine.

Providers implement stable contracts.

### 2.3 Deterministic before AI

Commands such as:

-   "Open Brave"
-   "Workspace two"
-   "Mute"
-   "Lock computer"

do not require an LLM.

Known commands should use deterministic parsing. More capable intent
providers can be introduced later as optional fallbacks.

### 2.4 Restricted actions instead of arbitrary shell execution

Intent providers should return structured actions, not shell commands.

For example:

``` json
{
  "action": "app.launch",
  "parameters": {
    "application": "brave"
  }
}
```

The Action Router decides whether the action exists and whether it is
permitted.

### 2.5 Separate UI from processing

The Omarchy Shell plugin provides the native user experience, but speech
recognition and command processing should live in a separate
backend/core.

### 2.6 Progressive capability

v0.1 should validate the architecture with a deliberately small command
set. Complexity should be added only after the provider and security
boundaries prove sound.

------------------------------------------------------------------------

## 3. High-Level Architecture

``` text
                         OMARCHY VOICE
                              │
                    ┌─────────┴─────────┐
                    │ Omarchy Shell UI │
                    │ Settings/Overlay │
                    └─────────┬─────────┘
                              │
                         Voice Core
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
 AUDIO CAPTURE           STT PROVIDER          INTENT PROVIDER
       │                      │                      │
   PipeWire            Faster-Whisper             Built-in
       │               whisper.cpp                Commands
       │               Voxtype?                    │
       │               Future STT                  │
       └──────────────────────┴──────────────────────┘
                              │
                        Structured Intent
                              │
                              ▼
                         Action Router
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
    Applications          Hyprland             System
       launch             workspace             lock
       close              focus                 audio
                          move                  power
```

------------------------------------------------------------------------

## 4. Components

### 4.1 Omarchy Shell Plugin

Responsibilities:

-   Voice activation UI
-   Listening/transcribing/executing status
-   Settings
-   Provider selection
-   Provider-specific configuration
-   Permission configuration
-   Confirmation dialogs
-   Error feedback
-   Optional microphone/status indicator

It should not implement STT itself.

Example:

``` text
┌──────────────────────────────────────────┐
│ Omarchy Voice                       🎙   │
│                                          │
│ Speech Recognition                       │
│ [ Faster-Whisper                    ▼ ]  │
│                                          │
│ Activation                               │
│ [ Push to talk                      ▼ ]  │
│                                          │
│ Command Engine                           │
│ [ Built-in                          ▼ ]  │
│                                          │
│ AI fallback                              │
│ [ Disabled                          ▼ ]  │
│                                          │
│ Privacy                                  │
│ 🟢 Processing stays on this computer     │
└──────────────────────────────────────────┘
```

------------------------------------------------------------------------

### 4.2 Audio Capture Layer

Audio capture should be independent from speech recognition.

``` text
Microphone
    ↓
PipeWire
    ↓
AudioCapture
    ↓
Normalized audio stream
    ↓
STT Provider
```

Possible future inputs:

-   Push-to-talk
-   Wake word
-   Always listening
-   Audio file
-   Different microphone
-   Remote/input device

The STT provider should receive audio rather than controlling the
microphone directly whenever practical.

------------------------------------------------------------------------

### 4.3 Speech-to-Text Provider API

Reference contract:

``` python
class STTProvider:
    def available(self) -> bool:
        ...

    def capabilities(self) -> STTCapabilities:
        ...

    def transcribe(self, audio, language=None) -> Transcription:
        ...
```

Potential providers:

``` text
providers/stt/
├── faster_whisper/
├── whisper_cpp/
├── voxtype/
├── parakeet/
├── cloud/
└── custom/
```

A provider should advertise capabilities rather than requiring the UI to
know provider-specific behavior.

Example metadata:

``` yaml
id: faster-whisper
name: Faster Whisper
type: stt

capabilities:
  offline: true
  streaming: true
  gpu: true
  cpu: true
  multilingual: true
  auto_language: true

settings:
  model:
    type: select
    default: large-v3-turbo

  device:
    type: select
    values:
      - cpu
      - cuda
```

This metadata can later drive UI generation automatically.

------------------------------------------------------------------------

## 5. Existing Omarchy Dictation / Voxtype

Existing dictation should initially remain independent from Omarchy
Voice.

``` text
F9
 ↓
Omarchy Dictation / Voxtype
 ↓
Speech → text
 ↓
Text inserted into focused application
```

Omarchy Voice has a different purpose:

``` text
Super + V
 ↓
Omarchy Voice
 ↓
Speech → structured intent
 ↓
Desktop action
```

Voxtype should be investigated as a possible STT provider or
integration.

It should only become a provider if it exposes a sufficiently clean way
to obtain recognized text without forcing its normal "type into the
active window" behavior.

**v0.1 must not depend on Voxtype.**

A future optimization could allow dictation and Omarchy Voice to share
the same local STT/model service, avoiding duplicate model loading and
GPU/CPU memory usage.

------------------------------------------------------------------------

## 6. Intent Provider

Input:

``` text
"Could you open Brave please?"
```

Output:

``` json
{
  "action": "app.launch",
  "parameters": {
    "application": "brave"
  }
}
```

### v0.1

Only the built-in deterministic intent provider is required.

It can support patterns and aliases such as:

``` text
open <application>
launch <application>
start <application>

close window

workspace <number>
go to workspace <number>

volume up
volume down
mute

lock computer
```

### Future

``` text
providers/intent/
├── builtin/
├── hermes/
├── ollama/
├── openai/
└── custom/
```

AI intent providers should be optional and should still produce the same
restricted structured-action format.

------------------------------------------------------------------------

## 7. Action Layer

The Action Router is the security boundary between understanding a
request and changing the system.

``` text
Transcription
     ↓
Intent Provider
     ↓
Structured Intent
     ↓
Action Router
     ↓
Permission Check
     ↓
Confirmation if required
     ↓
Action Implementation
```

Initial action API:

``` text
app.launch
app.close

window.close

workspace.switch

audio.volume_up
audio.volume_down
audio.mute

system.lock
```

Possible future namespaces:

``` text
media.*
display.*
bluetooth.*
network.*
clipboard.*
notifications.*
power.*
hermes.*
smart_home.*
```

The intent provider should never receive unrestricted shell execution
simply because it recognized a command.

------------------------------------------------------------------------

## 8. Security Model

Voice control can perform real actions on the user's computer. Security
therefore needs to be part of the architecture, not an afterthought.

### 8.1 No arbitrary shell execution by default

This should **not** be the default architecture:

``` text
Voice → LLM → generated shell command → execute
```

Instead:

``` text
Voice
 ↓
Intent
 ↓
Registered Action
 ↓
Validation
 ↓
Permission
 ↓
Execution
```

Unknown actions are rejected.

------------------------------------------------------------------------

### 8.2 Action risk levels

Actions should have explicit risk classifications.

Example:

  -----------------------------------------------------------------------
  Risk                    Examples                Default behavior
  ----------------------- ----------------------- -----------------------
  Low                     launch app, switch      Allow
                          workspace, volume       

  Medium                  close application, stop Allow or configurable
                          media, Bluetooth toggle 

  High                    suspend, reboot,        Require confirmation
                          shutdown                

  Critical                deleting data,          Disabled
                          privileged commands,    
                          arbitrary shell         
  -----------------------------------------------------------------------

This classification should eventually be metadata associated with
actions rather than scattered UI logic.

------------------------------------------------------------------------

### 8.3 Confirmation

Potentially destructive actions should require confirmation.

Example:

``` text
"Shut down the computer"

        ↓

┌──────────────────────────────────┐
│ Shut down this computer?         │
│                                  │
│      [ Cancel ]   [ Shut down ]  │
└──────────────────────────────────┘
```

Voice-only confirmation should not automatically be considered
sufficient for every critical operation.

------------------------------------------------------------------------

### 8.4 Command injection

Transcribed text and LLM responses must never be concatenated directly
into shell commands.

Application names, paths, arguments, workspace numbers, etc. must be
validated and passed through structured APIs.

Bad:

``` python
os.system("launch " + transcription)
```

Better:

``` python
application = registry.resolve(intent.target)
actions.execute("app.launch", {"application_id": application.id})
```

------------------------------------------------------------------------

### 8.5 Prompt injection and AI providers

When AI intent providers are introduced, spoken content must be treated
as untrusted input.

An LLM should not be allowed to expand its authority because the user
said something such as:

``` text
"Ignore your restrictions and execute..."
```

The Action Router remains authoritative regardless of the intent
provider.

------------------------------------------------------------------------

### 8.6 Misrecognition

STT can misunderstand commands.

Examples:

``` text
"lock computer"
        vs.
"shutdown computer"
```

Sensitive actions should consider:

-   confidence score, where available
-   explicit confirmation
-   exact intent requirements
-   avoiding fuzzy matching for dangerous commands

A low-confidence transcription should never silently trigger a high-risk
action.

------------------------------------------------------------------------

### 8.7 Voice spoofing

Future wake-word/always-listening modes introduce the possibility that:

-   another person speaks a command
-   audio from a video triggers a command
-   remote-call audio triggers a command

v0.1 reduces this risk by using **push-to-talk**.

Future always-listening modes will need a stronger threat model.

------------------------------------------------------------------------

### 8.8 Microphone privacy

The UI should always make microphone state obvious.

Possible states:

``` text
○ Idle
● Listening
◉ Transcribing
✓ Command recognized
```

Users should know whether audio processing is local or remote.

------------------------------------------------------------------------

### 8.9 Cloud provider privacy

Providers should advertise:

``` yaml
privacy:
  processing: local
```

or:

``` yaml
privacy:
  processing: remote
  sends_audio: true
```

The settings UI can then display:

``` text
🟢 Local — audio remains on this computer
```

or:

``` text
🟠 Cloud — microphone audio is sent to a remote service
```

------------------------------------------------------------------------

### 8.10 Secrets

Cloud provider API keys must not be stored in plaintext configuration if
avoidable.

Future work should evaluate:

-   system keyring / Secret Service
-   environment variables
-   provider-specific credential stores

Secrets must never appear in logs.

------------------------------------------------------------------------

### 8.11 Logging

Logs should be privacy-aware.

The system should distinguish:

``` text
technical logs
transcription history
action history
audio recordings
```

Audio recording should not be persisted by default.

Whether full transcription history should be stored at all needs an
explicit product decision.

------------------------------------------------------------------------

### 8.12 Plugin/provider trust

Third-party providers execute code on the user's machine.

Future provider installation should consider:

-   source/repository visibility
-   manifest validation
-   permission declarations
-   checksums/signatures where practical
-   explicit warnings for external providers
-   version compatibility
-   provider isolation/sandboxing possibilities

------------------------------------------------------------------------

## 9. Proposed Configuration

Example:

``` yaml
voice:
  activation: push-to-talk
  shortcut: SUPER+V

audio:
  device: default

stt:
  provider: faster-whisper

  faster-whisper:
    model: large-v3-turbo
    device: cuda
    language: auto

intent:
  provider: builtin
  fallback: disabled

actions:
  applications: true
  windows: true
  workspaces: true
  audio: true

  system:
    lock: allow
    suspend: confirm
    reboot: confirm
    shutdown: confirm

  shell:
    enabled: false

privacy:
  save_audio: false
  save_transcriptions: false
```

The exact format can change during implementation. The important part is
preserving clean ownership between components.

------------------------------------------------------------------------

## 10. MVP --- v0.1

The MVP is **not intended to solve every voice-control problem**.

Its purpose is to prove that the architecture works end-to-end.

### Reference implementation

``` text
Activation
    ↓
Push-to-talk (Super + V)
    ↓
PipeWire Audio Capture
    ↓
Faster-Whisper
    ↓
Built-in Intent Provider
    ↓
Action Router
    ↓
Omarchy / Hyprland action
```

### Initial commands

Target approximately 10 commands:

``` text
"Open Brave"
"Open terminal"
"Open Spotify"

"Close window"

"Workspace one"
"Workspace two"

"Volume up"
"Volume down"
"Mute"

"Lock computer"
```

Application launching should ideally use application discovery rather
than a permanently hard-coded application list.

### MVP exclusions

Do **not** include initially:

-   always-listening mode
-   wake-word detection
-   cloud STT
-   LLM command interpretation
-   Hermes integration
-   arbitrary shell commands
-   smart-home control
-   large command catalog
-   remote control
-   voice authentication
-   marketplace-ready provider ecosystem

These are post-MVP concerns.

------------------------------------------------------------------------

## 11. MVP Success Criteria

v0.1 is successful if:

1.  `Super + V` reliably starts/stops voice capture.
2.  Faster-Whisper transcribes the command locally.
3.  The built-in intent provider recognizes the supported commands.
4.  Unsupported commands fail safely.
5.  Actions execute through the Action Router.
6.  Dangerous/unregistered actions cannot bypass the router.
7.  Existing Omarchy dictation continues working independently.
8.  STT can be replaced through the provider interface without rewriting
    the core.
9.  The UI clearly indicates listening/transcription/execution state.
10. Errors are visible and do not leave the microphone or backend in a
    broken state.

------------------------------------------------------------------------

## 12. Things We Must Address After the MVP

The MVP validates the architecture. It is **not yet a product ready for
general distribution**.

### 12.1 Provider lifecycle

Define:

-   provider discovery
-   installation
-   enable/disable
-   versioning
-   compatibility
-   initialization
-   health checks
-   failure handling
-   upgrades

### 12.2 Capability negotiation

Different STT providers support different features:

``` text
streaming
GPU
CPU
language detection
confidence scores
timestamps
partial results
```

Core behavior must adapt to provider capabilities without
provider-specific hacks.

### 12.3 Application discovery

We need a reliable mapping from spoken names to installed applications.

Examples:

``` text
"browser" → default browser
"Brave" → brave-browser.desktop
"code" → Visual Studio Code
"files" → configured file manager
```

This likely requires `.desktop` discovery, aliases, defaults, and user
overrides.

### 12.4 Error and recovery model

Define behavior when:

-   microphone disappears
-   provider crashes
-   GPU runs out of memory
-   model is unavailable
-   transcription times out
-   intent is ambiguous
-   action fails
-   Omarchy/Hyprland changes underneath us

### 12.5 Performance targets

Measure:

``` text
activation latency
audio capture latency
STT latency
intent latency
action latency
memory usage
GPU memory usage
idle resource usage
```

A voice command should feel immediate.

### 12.6 Model lifecycle

Local STT introduces:

-   model download
-   model selection
-   storage
-   updates
-   disk requirements
-   first-run experience
-   GPU/CPU compatibility

### 12.7 Shared STT service

Investigate whether one persistent STT service can serve:

-   Omarchy Voice
-   Voxtype/dictation
-   other applications

This could avoid loading multiple copies of the same model.

### 12.8 Accessibility

Consider:

-   keyboard-only configuration
-   visible status
-   screen-reader-compatible UI
-   adjustable timeout
-   users with speech differences
-   configurable language/locale
-   feedback without requiring sound

### 12.9 Internationalization

Commands should not be inherently English-only.

Eventually:

``` text
"Open Brave"
"Abre Brave"
"Ouvrir Brave"
```

should map to the same structured action.

The action API should remain language-neutral.

### 12.10 Testing

We will need several test layers:

``` text
Unit
├── intent parsing
├── action validation
├── provider metadata
└── permission policy

Integration
├── audio → STT
├── STT → intent
├── intent → action
└── provider failure

Security
├── malformed intents
├── injection attempts
├── dangerous actions
└── permission bypass

End-to-end
└── microphone → desktop action
```

Recorded test audio can make STT tests reproducible without requiring a
live microphone.

### 12.11 Observability

Developer diagnostics should expose enough information to troubleshoot:

``` text
selected microphone
provider
model
provider status
transcription latency
recognized intent
action result
```

without leaking secrets or unnecessarily storing private speech.

### 12.12 Packaging and installation

Before public distribution, define:

-   dependencies
-   Python/runtime management
-   CUDA optionality
-   CPU fallback
-   model installation
-   Omarchy plugin installation
-   upgrade/uninstall behavior
-   configuration migration

### 12.13 Omarchy compatibility

Omarchy evolves quickly.

Keep Omarchy-specific integrations behind adapters where possible so
changes to:

-   Omarchy Shell
-   Quickshell
-   Hyprland
-   launcher behavior
-   plugin APIs

do not require rewriting the voice core.

------------------------------------------------------------------------

## 13. Future Capabilities

These are intentionally outside v0.1 but should remain architecturally
possible.

### Wake word

``` text
"Hey Omarchy"
      ↓
Listening
```

Requires careful privacy, resource, and spoofing analysis.

### AI fallback

``` text
Built-in parser
      ↓
No deterministic match
      ↓
Optional Intent Provider
      ↓
Hermes / Local LLM / Cloud AI
```

AI should still return registered structured actions.

### Compound commands

``` text
"Open terminal on workspace three"
```

could produce:

``` text
workspace.switch(3)
app.launch("terminal")
```

This requires sequencing, failure semantics, and permission checks.

### User-defined aliases

``` yaml
aliases:
  browser: brave
  editor: code
  music: spotify
```

### Extensible action providers

Third-party integrations could eventually add actions without modifying
core.

### Context awareness

Future commands might understand:

``` text
"Close this"
"Move this to workspace four"
"Open another terminal here"
```

using current window/workspace context.

### Hermes integration

Hermes can eventually handle requests that genuinely benefit from an
agent.

Example:

``` text
"Ask my reviewer agent to review the current repository changes."
```

This should be a separate integration rather than making Hermes
mandatory for basic desktop control.

------------------------------------------------------------------------

## 14. Suggested Repository Structure

Initial proposal:

``` text
omarchy-voice/
├── README.md
├── docs/
│   ├── architecture.md
│   ├── security.md
│   └── providers.md
│
├── plugin/
│   ├── manifest.json
│   └── qml/
│
├── core/
│   ├── audio/
│   ├── stt/
│   ├── intent/
│   ├── actions/
│   ├── permissions/
│   └── config/
│
├── providers/
│   ├── stt/
│   │   └── faster_whisper/
│   └── intent/
│       └── builtin/
│
├── actions/
│   ├── applications/
│   ├── windows/
│   ├── workspaces/
│   ├── audio/
│   └── system/
│
└── tests/
    ├── unit/
    ├── integration/
    ├── security/
    └── audio/
```

This is a starting point, not a commitment to a monorepo or Python
package layout.

------------------------------------------------------------------------

## 15. Proposed Implementation Phases

### Phase 0 --- Validate assumptions

Before substantial coding:

-   Verify current Omarchy Shell plugin APIs.
-   Investigate Voxtype's interfaces.
-   Confirm reliable PipeWire capture options.
-   Confirm application discovery strategy.
-   Prototype Faster-Whisper transcription from captured audio.
-   Validate Hyprland/Omarchy actions needed by the MVP.

### Phase 1 --- Headless proof of concept

Build:

``` text
CLI → record → transcribe → parse → print structured intent
```

No QML required yet.

Goal: validate core contracts.

### Phase 2 --- Safe action execution

Introduce:

-   Action Registry
-   permission policy
-   application launch
-   workspace switching
-   audio actions
-   lock action

Test malicious and malformed inputs.

### Phase 3 --- Omarchy UI

Add:

-   `Super + V`
-   listening overlay
-   status feedback
-   provider/settings UI
-   error states

### Phase 4 --- Provider validation

Add a second STT provider or a fake/test provider.

This is important: an abstraction is not truly validated if only one
implementation ever uses it.

### Phase 5 --- Hardening

Focus on:

-   failure recovery
-   logging/privacy
-   configuration migration
-   security tests
-   latency
-   packaging
-   CPU-only behavior

### Phase 6 --- Broader beta

Only after the architecture is stable:

-   additional languages
-   more commands
-   additional STT providers
-   user-defined aliases
-   optional AI fallback
-   Hermes integration

------------------------------------------------------------------------

## 16. Key Architectural Decisions to Resolve

Before or during v0.1, document decisions for:

1.  **Core implementation language** --- likely Python for the initial
    STT ecosystem, but the backend boundary should remain explicit.
2.  **Plugin ↔ backend IPC** --- process invocation, local socket,
    D-Bus, or another mechanism.
3.  **Audio representation** --- streaming PCM versus temporary WAV/file
    interfaces.
4.  **Provider process model** --- in-process plugins versus isolated
    provider processes.
5.  **Application registry** --- how `.desktop` entries, defaults,
    aliases, and commands are resolved.
6.  **Permission model** --- action-level versus namespace-level
    permissions.
7.  **Confirmation API** --- backend policy versus frontend
    presentation.
8.  **Provider schema format** --- settings and capabilities.
9.  **Configuration format/location**.
10. **Persistent backend** --- whether keeping STT models loaded is
    worth the idle memory footprint.
11. **Streaming support** --- required contract or optional capability.
12. **Transcription confidence** --- normalized across providers or
    provider-specific metadata.

These should become ADRs (Architecture Decision Records) as decisions
are made.

------------------------------------------------------------------------

## 17. Immediate Next Steps

Recommended order:

1.  Create the repository and documentation skeleton.
2.  Add this architecture as the initial design document.
3.  Create ADR infrastructure (`docs/adr/`).
4.  Investigate Voxtype specifically to determine whether it can act as
    an STT provider or share an STT service.
5.  Define the first version of:
    -   `STTProvider`
    -   `IntentProvider`
    -   `Action`
    -   `ActionResult`
    -   `PermissionPolicy`
6.  Prototype PipeWire → Faster-Whisper locally.
7.  Implement built-in parsing for the MVP command set.
8.  Implement an Action Registry with no arbitrary shell execution.
9.  Add unit/security tests before connecting actions to the real
    desktop.
10. Build a headless CLI proof of concept.
11. Connect the core to Omarchy Shell only after the backend contracts
    work.
12. Add a second/mock STT provider to verify provider agnosticism.

------------------------------------------------------------------------

## 18. Definition of v0.1

v0.1 is **an architectural MVP, not a public finished product**.

It proves:

> A user can press a shortcut, speak a supported command, have an
> interchangeable local STT provider transcribe it, have a deterministic
> intent engine produce a structured action, and have a permission-aware
> action router safely execute that action in Omarchy.

Everything beyond that should be treated as iteration rather than a
prerequisite for proving the design.

------------------------------------------------------------------------

## 19. Long-Term Direction

The architecture should make this progression possible without rewriting
the core:

``` text
v0.1
Push-to-talk
Faster-Whisper
Built-in commands
Small action set
        │
        ▼
v0.x
Multiple STT providers
More languages
Aliases
Better UI
        │
        ▼
v1.x
Optional AI intent providers
Hermes
Compound commands
Provider ecosystem
        │
        ▼
Future
Wake word
Context-aware commands
Third-party actions
Shared local speech service
Other desktop frontends
```

The central principle should remain:

> **Speech engines understand audio. Intent engines understand requests.
> Actions change the system. No component should gain more authority
> simply because another component is more intelligent.**
