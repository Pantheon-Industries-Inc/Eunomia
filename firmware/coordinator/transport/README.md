# `firmware/coordinator/transport/` — the radio/transport layer (swappable)

**Filled in a later run.** WiFi-AP hosting + the OSC client (fire-and-forget, single serialized
client, no background polling) + the telnet client (the sidecar write path). This is the
hardware-coupled, **swappable** module — the SoftAP load-test hedge: if SoftAP proves marginal under
sustained load, you replace `transport/`, not the trigger logic in `core/`.
