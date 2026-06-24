# `ingest/qc/`

**Filled in its own run.** The two deterministic QC stages (open-taxonomy, config thresholds,
default-ok): IMU motion-QC (from the IMU the camera embeds, extracted here from the front lens) +
video/container-QC. Writes flags + reasons + a cohort-relative score into the release record. A
learned/VLM stage is a separate future concern. (CONTRACT §4.1.)
