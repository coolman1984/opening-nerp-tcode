# Lessons

1. Enterprise browser automation fails silently; verify each observed outcome.
2. Poll for the specific required control; never use fixed sleeps.
3. Generated UI identifiers and rendered grid rows are not stable data APIs.
4. G-MES business policy must remain outside generic screen/query/export
   capabilities so a report-specific assumption cannot silently affect another
   screen.
5. A CLI stays shallow when it delegates all project behavior through one
   application seam; input validation may live behind that seam to keep it
   side-effect free.
6. Credential migration is state mutation and must be explicit, idempotent,
   copy-only, and separate from read-only diagnostics.
7. Package proof belongs near the first usable CLI surface, not after further
   migration work; `version` and command-help smoke checks require no browser.
8. Legacy scripts are evidence, not dead code: retain them until standalone
   read-only live verification proves parity.
