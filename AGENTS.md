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

## Standalone G-MES routing — ⚠️ REVERSED 2026-09-13: `src/gmes` IS FROZEN

**The paragraph that stood here told you to put every behaviour change in
`src/gmes/`. That is now backwards.** By the project owner's decision, the
production core is the flat legacy engine at the repo root — `gmes_core.py`,
`gmes_login.py`, `gmes_common.py`, `gmes_open_screen.py`, `cdp_common.py`
and friends. Behaviour changes go THERE.

`src/gmes/` is quarantined pending layer-by-layer removal:

- **Do not add features to it, do not fix bugs in it, and do not run it**
  (`python -m gmes`, `gmes.bat`, `GMES.exe` are all off-limits for now).
- The two engines share CDP port 9444 and the Chrome profile copy at
  `%LOCALAPPDATA%\Google\Chrome\CDP Profile`, so running the new one can
  change the state the legacy one later finds. The isolation is in the
  imports only, never at runtime.
- Frozen snapshot: `archive/standalone-gmes-before-removal` @ `59eb838`.
- Removal order, and which step is next: the restoration table at the top of
  [CURRENT_STATE.md](CURRENT_STATE.md). One step per commit; stop on red.

Read **section 0 of [CLAUDE.md](CLAUDE.md)** first — it is the authority, and
it outranks any document here that still describes the old direction.

The rules below still describe the internal layering of `src/gmes` and remain
accurate *about that package*; they are not permission to work in it.

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
