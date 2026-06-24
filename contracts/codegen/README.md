# `contracts/codegen/` — one source, three targets

`generate.py` reads a **language-neutral YAML** schema and emits three targets so every stack
consumes the *same* definition:

```
contracts/_proof/ping.schema.yaml   (the neutral source — 0a proof)
            │   uv run --no-project --with pyyaml python contracts/codegen/generate.py
            ▼
contracts/_generated/
  ├── cpp/eunomia_ping.h                              # firmware: struct + parse/serialize (no deps)
  ├── python/eunomia_contracts/{ping.py,__init__.py}  # dataclass + pure-stdlib hard-vs-warn validator
  └── jsonschema/ping.schema.json                     # the conformance gate + web validation
```

## How it's invoked

- `make codegen` → `uv run --no-project --with pyyaml python contracts/codegen/generate.py`.
- `--no-project` keeps codegen independent of the workspace sync (it must run before `uv sync` can
  build `eunomia-contracts`, whose package *is* the generated tree). PyYAML is fetched ephemerally so
  the shipped `eunomia_contracts` validator stays pure-stdlib.

## Outputs are committed + drift-gated

`_generated/` is committed (firmware can `#include` the header; the conformance gate has the schema
without a build step). The **codegen-drift gate** keeps it honest:

```
make drift   #  == make codegen && git diff --exit-code contracts/_generated
```

Output is deterministic (sorted keys, no timestamps) so the drift check is meaningful. **Never
hand-edit `_generated/`** — edit the source and regenerate (see `.claude/rules/contracts.md`).

## The size rule (OQ-10, approved)

The generator is a **small hand-written generator, kept under ~150 lines of obvious code**. The
neutral-YAML + small-generator choice was made *because* the contract's pure-stdlib hard-vs-warn
semantics + the hardware interface ports don't map cleanly onto protobuf / JSON-Schema-as-source. If
this ever starts needing real complexity (nested types, the interface ports, conditional validation),
**STOP and flag it** rather than growing the generator.
