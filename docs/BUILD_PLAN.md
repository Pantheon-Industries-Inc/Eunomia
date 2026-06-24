# Eunomia — Build Plan

The phase sequence (from `MODULE_MAP.md` "build order") + the current scope. Mirrors Hermes's
`docs/BUILD_PLAN.md`: thin, kept current, points at the active run.

## Phase sequence (dependency-driven; parallel only where truly independent)

1. **Foundation** (serial, alone) — repo skeleton + frozen `contracts/` + conventions + the ADR +
   per-language gates + the ported substrate (adopting the existing config as-is). The spine
   everything else builds on. **(Run 0)**
2. **Bench harness** (after Foundation) — run the load-test gate against the proven firmware for the
   hardware verdict.
3. **Coordinator firmware** + **camera-image** in parallel (independent; separate worktrees), the
   coordinator proceeding with the SoftAP verdict known.
4. **ingest / edge / consoles** — after the capture edge is proven (their own phases; the consoles can
   parallelize since each is an island). Revisit the map after Foundation.

## Current scope — Run 0a (Foundation skeleton)

**In:** the 8 module directories + per-module READMEs; the polyglot build shells (uv Python 3.12
workspace mirroring Hermes; PlatformIO ESP32 coordinator); the **stub `contracts/` + codegen proof**
(one `ping` example → C++ header + Python type + JSON Schema, exercised by the conformance harness);
per-language gates + the cross-language conformance + codegen-drift gates (local == CI); `.claude/`
deterministic enforcement (format + secret-block hooks, the `reviewer` subagent, a lean `CLAUDE.md`);
the ADR; `.gitignore` / root `README.md` / lockfiles.

**Out (→ later runs):** the real contract schemas (**Run 0b**, against this harness); any
firmware/ingest/edge/console logic; the real substrate host scripts; the web stack; edge-sync policy;
how Hermes consumes the contract; console auth/PII; QC thresholds.

**Next:** Run 0b — pour the real CONTRACT §2–§4 schemas into `contracts/` against the proven harness.

### Carry into Run 0b (foundation notes, not 0a fixes)

These are deliberate 0a simplifications to revisit when the real schemas land — recorded so they are
not lost:

1. **Make codegen hermetic.** PyYAML is currently supplied ephemerally (`uv run --no-project --with
   pyyaml …`) so the shipped `eunomia_contracts` validator stays pure-stdlib. In 0b, **pin PyYAML in a
   codegen-specific dependency group** so regeneration is reproducible/hermetic (and have CI install
   that group for the drift gate) rather than relying on an ephemeral fetch.
2. **JSON Schema validation is a hand-rolled stdlib subset-checker** (in the conformance test) today.
   In 0b, **either adopt a real JSON Schema validator (`jsonschema`) or explicitly document the format
   as "our dialect + its reference validator"** — because the real contract's nested objects and the
   hard-vs-warn field split are exactly where a subset-checker would diverge from a real validator.
3. **The ~150-line generator budget will be under pressure** when the real (nested, hard-vs-warn,
   modality-general, interface-port) schemas land. The **STOP-and-flag rule (OQ-10) still stands**: if
   the generator starts needing real complexity, stop and flag rather than growing it into a framework
   (consider externalizing more into templates, or splitting per-target emitters).
