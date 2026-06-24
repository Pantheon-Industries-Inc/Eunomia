# `contracts/codegen/` — one source, three targets

`generate.py` reads each **language-neutral YAML** schema under `contracts/<area>/*.schema.yaml` and
emits three targets so every stack consumes the *same* definition:

```
contracts/{sidecar,release,events}/*.schema.yaml        (the neutral sources)
            │   uv run --no-project --with-requirements contracts/codegen/requirements.txt \
            │       python contracts/codegen/generate.py   (then ruff-format the generated Python)
            ▼
contracts/_generated/
  ├── cpp/eunomia_detail.h + eunomia_<entity>.h          # firmware: flat field-bag struct + parse/serialize
  ├── python/eunomia_contracts/{<entity>.py, _semantics.py, __init__.py}
  └── jsonschema/eunomia-<entity>.schema.json            # the conformance gate + browser/ajv validation
```

The field DSL: `name · type(int|number|string|bool|object|array) · required(hard|warn) · description`,
plus optional `enum:[…]`, `non_empty:true`, `nullable:true`, `conditional:true` (the v1-extra hard set),
`items:<type>` (array), `fields:[…]` (object — **one** nesting level). C++ is emitted only for the
firmware-relevant records (`targets:` includes `cpp`); release + sync-delta are Python + JSON Schema.

## How it's invoked

- `make codegen` → generate under the **pinned codegen deps** (`requirements.txt`, hermetic; replaces
  the 0a ephemeral `--with pyyaml`), then `uv run ruff format contracts/_generated/python`. `--no-project`
  is required: codegen produces the tree that *is* the `eunomia-contracts` package, so it must run before
  uv could build that package. The generator emits valid Python; ruff owns the exact format.
- `_semantics.py` (the pure-stdlib validation overlay) and `eunomia_detail.h` (the shared C++ parse
  helpers) are **vendored verbatim** from `templates/` — hand-written sources, edited in `templates/`,
  never in `_generated/`.

## Outputs are committed + drift-gated

`_generated/` is committed (firmware `#include`s the headers; the conformance gate has the schemas
without a build step). The **codegen-drift gate** keeps it honest:

```
make drift   #  == make codegen && git diff --exit-code contracts/_generated   (must be 0)
```

Output is deterministic (sorted keys, fixed field order, ruff-canonical Python) so the drift check is
meaningful. **Never hand-edit `_generated/`** — edit the source/template and regenerate.

## The size rule (OQ-10) + Run 0b budget verdict

The generator stays a **small, obvious, hand-written generator** — no framework. Run 0b added "more
field-types" (enum/nullable/array/`minLength`), **one** bounded conditional rule (the v1-extra hard set),
and **one** level of object nesting. It did NOT cross the STOP-and-flag line (no recursion, no type
system, no rule-DSL — real cross-field LOGIC is hand-written in `_semantics`, not generated). The
interface shape that *would* cross it (operation signatures) is deferred to 0c.

**OQ-8 note (per-emitter split):** kept as a single, sectioned `generate.py` rather than an `emitters/`
subpackage — an intra-codegen import breaks `mypy .`-from-root resolution under the no-`[tool.mypy]`-config
gate. The file exceeds the ~150-line guideline but stays obvious; see the report for the line count.
