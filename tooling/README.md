# `tooling/` — engineering tooling (Python)

**Single responsibility:** engineering tooling that supports the build but is not shipped behavior.

**Dependency rule:** depends only on `contracts/`. Never imported by ingest/edge/consoles/firmware.

## Layout

| Path | Responsibility |
|---|---|
| `bench-harness/` | runs the gates against a rig. **Two layers**: a thin real serial/telnet IO shell + a hardware-free core that replays recorded logs (so it's testable + CI-able with no rig). Built early; the first thing run against the proven firmware for the load-test verdict. |

> Run 0a: the `eunomia-bench-harness` workspace member is a shell (package + README only). It is a
> uv workspace member so the Python gates have a second package to enforce the dependency law against.
