# Rule: substrate/

- **The substrate interface is FROZEN to the existing on-site deploy.** Eunomia *contains* the
  substrate definition but does NOT change its shape/config/layout — a setup the operator already
  deployed (from the existing `styx/` folder) must stay valid. (Decisions D-8 / D-12.)
- When real host scripts are vendored, vendor them **unchanged**. Any real substrate change is
  deliberate + communicated, never a surprise that breaks a running box.
- Identity/config deployment is a **non-destructive merge** (drift-detect + backup), never a
  destructive overwrite (the camera_map incident lesson; CONTRACT §6).
- The drain/route/wipe *behavior* is Eunomia's (`ingest/` + a drain module); the substrate is only the
  host floor, used through the frozen interface (ZFS path, Sipolar resolution, the udev trigger, the
  status-JSON shape, camera_map location).
