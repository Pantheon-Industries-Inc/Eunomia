# `firmware/coordinator/core/` — the trigger logic (pure, off-target testable)

**Filled in a later run.** The trigger state machine, episode/ordinal logic, sidecar assembly, the
phantom-press guarantee (a take only starts when both cameras have acknowledged — spamming is
harmless by design), and the instant touch-acknowledgement UI state machine. Implements
`CoordinatorPort`.

**Hardware-free + off-target testable** — the durable ordinal is written to flash before the counter
advances; the network worker runs on a dedicated core so the UI never stalls. Tested with no rig via
`pio test -e native` (the one-machine rule).
