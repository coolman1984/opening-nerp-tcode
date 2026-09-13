# Project Eye

The standalone G-MES migration is the future architecture. Legacy scripts
remain frozen comparison targets until read-only live verification proves
replacement. N-ERP is a separate system and is never imported by `src/gmes`.

```text
SYSTEM: Enterprise automation
  DOMAINS: N-ERP (legacy, frozen) | G-MES standalone
    ENTRANCES: GMES_Workflow.bat → workflow | gmes.bat → CLI | run_gmes_workflow.py → workflow
    COMPONENTS: CLI → application façade → domain capabilities
      CODE: cli | application | auth | browser | nexacro | discovery |
            screens | query | export | profiles | contracts
        RUNTIME: Chrome CDP profile copy, %LOCALAPPDATA%\GMES, user-selected exports
```

`cli/` parses and renders only. `application/facade.py` is its sole project
seam. Application use cases orchestrate domain capabilities; domains do not
depend on legacy flat G-MES modules. Specialized business policy belongs in
`examples/` or a separate consumer and reaches generic G-MES only through the
application façade. `gmes migrate` is the only credential-copy command;
`gmes credentials set` is the separate explicit credential replacement path.
future `gmes doctor` is diagnostic and read-only.

```text
Every supported entrance reaches the same path:

```text
GMES_Workflow.bat / run_gmes_workflow.py / gmes.bat
  → CLI presentation → application operation → auth/connect
  → capability → verify → cleanup → result
```

The old interactive filename is retained for operator convenience only. It is
not allowed to own a browser session or automation decision, and no behaviour
may be implemented twice in a flat legacy script and the package.
```

Application owns the browser/CDP session and releases it before returning.
DPAPI owns credentials; `%LOCALAPPDATA%\GMES` owns profiles, logs,
screenshots, evidence, config/cache, and default exports. The selected export
directory owns explicitly requested output files. The established Chrome-owned
copy of the user’s Default profile stays at `%LOCALAPPDATA%\Google\Chrome\CDP
Profile`; it is an explicit exception, never the real Chrome profile. CLI and
specialized consumers own neither CDP sessions nor credentials/profile state.

`gmes doctor` is a read-only observer of this journey and its prerequisites;
only `gmes migrate` can copy an existing credential store; only explicit
`gmes credentials set` may replace a credential.

The machine-enforced version of these rules is
`tests/unit/test_architecture_rules.py`; the navigable graph and rule source
are `.project-eye/graph.yaml` and `.project-eye/rules.yaml`.
