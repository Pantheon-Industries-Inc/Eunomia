# `substrate/` — the ported host substrate (interface FROZEN)

**Single responsibility:** the immovable host layer the on-site ingest box needs — ZFS pool, the
multi-slot card-reader (Sipolar) port-mapping, the udev plumbing, the systemd units, the install
scripts. The host *floor* Eunomia's behavior runs on.

**Dependency rule:** a frozen interface. Eunomia *contains* the substrate definition but does **not**
change its shape/config/layout — a setup the on-site operator already deployed (from the existing
`styx/` folder) stays valid. The installer is an **idempotent superset**: if the substrate is already
set up, Eunomia detects it and does not redo it, only layers the unified software on top. Any real
substrate change is deliberate + communicated, never a surprise that breaks a running box. (Decisions
D-8 / D-12.)

**The drain/route/wipe *behavior* is Eunomia's** (it lives in `ingest/` + a drain module); the
substrate is just the host floor, exposed through the frozen interface (the ZFS pool path, the Sipolar
resolution algorithm, the udev trigger contract, the status-JSON shape, the camera_map location). Note
`camera_map` becomes a **projection** of Eunomia's identity model, not an independent source (D-9).

## Run 0a scope (explicit)

0a sets up this directory + this frozen-interface README + states where the existing host config
**will** be vendored. It does **NOT** copy real host scripts (none are present in the repo to vendor).
When they are provided, they are vendored **unchanged** (the interface is frozen to the existing
deploy).
