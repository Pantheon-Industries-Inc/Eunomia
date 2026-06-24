# `tooling/bench-harness/`

**Single responsibility:** runs the gates against a rig for the hardware verdict (the SoftAP
load-test). **Two layers:** a thin real serial/telnet IO shell + a hardware-free core that replays
recorded logs, so the harness is testable and CI-able with no rig (the one-machine rule).

**Dependency rule:** depends only on `eunomia_contracts`.

> Run 0a: a shell (`src/eunomia_bench_harness/` + this README). The replay core + IO shell are built
> after Foundation, as the first thing run against the proven firmware.
