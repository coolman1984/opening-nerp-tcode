# Project Eye

The standalone G-MES migration is the future architecture. Legacy scripts
remain frozen comparison targets until read-only live verification proves
replacement. N-ERP is a separate system and is never imported by `src/gmes`.

```text
SYSTEM: Enterprise automation
  DOMAINS: N-ERP (legacy, frozen) | G-MES standalone
    COMPONENTS: CLI → application façade → domain capabilities
      CODE: cli | application | auth | browser | nexacro | discovery |
            screens | query | export | profiles | contracts
        RUNTIME: Chrome CDP, %LOCALAPPDATA%\GMES, user-selected exports
```

`cli/` parses and renders only. `application/facade.py` is its sole project
seam. Application use cases orchestrate domain capabilities; domains do not
depend on legacy flat G-MES modules. Specialized business policy belongs in
`examples/` or a separate consumer and reaches generic G-MES only through the
application façade. `gmes migrate` is the only credential-copy command;
future `gmes doctor` is diagnostic and read-only.

The machine-enforced version of these rules is
`tests/unit/test_architecture_rules.py`; the navigable graph and rule source
are `.project-eye/graph.yaml` and `.project-eye/rules.yaml`.
