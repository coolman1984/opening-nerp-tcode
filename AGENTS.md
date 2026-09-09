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
