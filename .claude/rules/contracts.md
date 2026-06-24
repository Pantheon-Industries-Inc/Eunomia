# Rule: contracts/

- **`contracts/` is THE SPINE — it imports nothing internal.** Everything depends on it; it depends on
  no other module. (Enforced by import-linter: `eunomia_contracts` is forbidden from importing any
  other `eunomia_*` package.)
- **Never hand-edit `contracts/_generated/`.** It is codegen output, committed and drift-gated. Edit
  the neutral source under `contracts/<area>/` and run `make codegen`. See the `codegen` skill.
- A contract change is **its own reviewed PR** with a `schema` version bump + changelog (CONTRACT §5).
  Additive only: add fields, never rename — old files must still validate.
- Generated output must stay deterministic and ruff-format-clean as emitted.
