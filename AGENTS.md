# Agent instructions

The operating rules for this project are in **[CLAUDE.md](CLAUDE.md)**.
Read that file completely before your first tool call, whatever agent you
are.

Then read **[HISTORY.md](HISTORY.md)** before changing any automation logic.
It records every failure this project has hit and why. Most of them produced
no error at all, so the cause is rarely guessable from the code alone.

Three rules matter more than the rest:

1. **Any behaviour change requires a HISTORY.md entry in the same commit.**
2. **Never delete or modify the user's real Chrome profile**, and never
   write credentials anywhere but the DPAPI store.
3. **Never sleep a fixed duration.** Poll until you observe the thing you
   need, with a generous cap.

## Standalone G-MES routing

For work under `src/gmes/`, read [PROJECT_EYE.md](PROJECT_EYE.md),
`.project-eye/rules.yaml`, and [CURRENT_STATE.md](CURRENT_STATE.md) before
editing. The standalone package is the active architecture; the flat
`gmes_*.py` scripts are frozen comparison paths and must not be changed or
imported by migrated domains unless the user explicitly asks.

- `cli/` may import only `application/facade.py`; it parses, calls one
  application operation, renders, and exits. It never reaches domain modules
  directly or owns a browser/CDP/WebSocket session.
- Application use cases orchestrate domain capabilities. Report-specific
  policy belongs in `examples/` or another external consumer, never generic
  `src/gmes/application`.
- Runtime state belongs only under `%LOCALAPPDATA%\GMES`. `gmes migrate` is
  the explicit credential-copy action; present and future `gmes doctor`
  diagnostics are read-only.
- Run `tests/unit/test_architecture_rules.py` with the normal offline gates
  after changing package structure or imports.
