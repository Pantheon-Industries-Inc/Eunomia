---
name: codegen
description: How to add or change a contract schema and regenerate the C++/Python/JSON-Schema targets. Use when editing anything under contracts/ or when the codegen-drift gate is red.
---

# Contract codegen

`contracts/` is **one source, three targets**. You edit a language-neutral YAML schema; the generator
emits a C++ header, a Python type + pure-stdlib validator, and a JSON Schema.

## Add or change a schema

1. Edit (or add) the neutral source under `contracts/<area>/` (in Run 0a the only source is the
   throwaway `contracts/_proof/ping.schema.yaml`). Fields: `name` · `type` (int|number|string|bool) ·
   `required` (hard|warn) · `description`. `hard` = corruption invalidates the record; `warn` =
   recoverable, surfaced in triage.
2. Regenerate: `make codegen`.
3. Add/extend golden fixtures under `contracts/conformance/fixtures/<schema>/{valid,invalid}/` and a
   conformance test if it's a new schema.
4. Run the conformance gate: `uv run pytest` (Python + schema) and `pio test -e native` (C++).
5. Bump the `schema` version + changelog if the change is consumer-visible (CONTRACT §5). Additive
   only: add fields, never rename.

## Rules

- **Never hand-edit `contracts/_generated/`** — it is overwritten by codegen and guarded by the drift
  gate (`make drift` = `make codegen && git diff --exit-code contracts/_generated`). Edit the source.
- Output must stay **deterministic** (sorted keys, no timestamps) so the drift gate is meaningful.
- Generated Python must be **ruff-format-clean as emitted** (the generator emits already-formatted
  code) so the format gate and the drift gate don't fight.
- Keep `generate.py` under ~150 lines of obvious code. If a change needs real complexity (nested
  types, the interface ports, conditional validation), **STOP and flag it** — do not grow the
  generator into a framework (the approved OQ-10 rule; see `contracts/codegen/README.md`).
