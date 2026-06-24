# `ingest/orchestrator/`

**Filled in its own run.** The parallel, idempotent runner: one worker per card-dump, per-dump
done-markers, hardlinks (never copies), the staging-tree contract. Built for ~100 kits/hr; the IMU
extraction is the throughput knob.
