# ADR 0002: NoNewPrivileges is not set on the user service

Status: accepted.

## Context

The systemd user unit previously set `NoNewPrivileges=yes`. The kernel propagates
this flag to every descendant process, so applications launched through the
voice backend inherited it too. A terminal opened by voice ("open terminal")
could not run `sudo` at all:

```
sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
```

This broke the normal desktop contract: a terminal launched by voice should
behave like a terminal launched from the bar or a keybinding.

## Decision

Remove `NoNewPrivileges=yes` from `integrations/omarchy-voice.service`.

The flag added little defense in depth here: the service already runs as the
signed-in user in the user's own slice, and the same user's other session
processes (bar, terminal launcher) run without it. An attacker who can reach
the voice socket is already same-user. The hardening value of blocking sudo in
launched GUI apps does not justify breaking them.

The security boundary stays in the action router: argv-only execution, a fixed
command grammar, no shell, and no arbitrary-command action. Users cannot speak
`sudo ...` directly; this change only restores normal privileges inside
applications the user explicitly launches.

## Consequences

- Terminals opened by voice can use `sudo` normally.
- `systemd-analyze --user security omarchy-voice` now reports
  `NoNewPrivileges=` as not applied; this is intentional.
- Reinstall the unit and run `systemctl --user daemon-reload && systemctl --user restart omarchy-voice.service`
  for the change to take effect; already-running services keep the old flag
  until restarted.
- Close all windows of an already-running single-instance terminal (such as
  Ghostty) before testing again. New windows may be handed to that old process,
  which cannot clear its inherited `NoNewPrivs` flag. Do not kill the terminal
  hosting an active session without first saving work and exiting it.
