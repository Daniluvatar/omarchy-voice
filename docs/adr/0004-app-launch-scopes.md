# ADR 0004: Launch applications in independent user scopes

Status: accepted for the local app-launch workflow; one live GUI app checked.

## Context

A process session (`start_new_session=True`) does not separate a child from its
parent systemd service cgroup. The voice backend launched applications in
`omarchy-voice.service`, whose default `KillMode=control-group` stops every
remaining process in that cgroup on restart. Applying a saved alias restarts the
service, and the user reports that other voice-launched applications close.

## Decision

Run validated app-launch argv through `systemd-run --user --scope --quiet
--collect --` using the existing detached, no-shell launcher. A transient user
scope owns the launcher and its descendants independently of the voice service.
Do not change the service's kill policy: stopping it must still clean up its own
capture and STT workers. If the user manager or scope creation fails, report a
launch error; never silently fall back to service-owned GUI processes.

The router still validates permissions and desktop IDs before invoking the
launcher. Transcribed text never becomes executable argv or a shell fragment.
The existing brief startup observation and async reaper remain, but a successful
scope launch does not prove that a desktop window appeared or that a GUI app
continued running after the launcher exited.

## Verification and limits

The unit/security/integration suite and native QML harness passed. In an
isolated transient user service, the real `_launch_application` created a scope
under `app.slice`; a harmless Python child wrote a survival marker after its
parent service was stopped. The live voice service and user's GUI applications
were not restarted or closed in that probe. After installing the fix, a live
Brave window launched through the voice daemon remained visible with the same
PID in a separate application scope after a voice-service restart. The user
later reported that saving/applying a recorded Spotify phrase did not close
TopTracker or other apps; the alias mapping and dry-run route were read back,
but microphone recognition was not independently instrumented. Other app
types, scope handoff under load, and failure/error reporting still require
acceptance testing before issue #4 can close.

`systemd-run` and a functioning systemd user manager are now required for app
launches. Manual `serve` also uses scopes; dry-run planning still reports the
underlying `omarchy`/`gio` argv rather than the execution wrapper.
