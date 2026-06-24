# `ingest/join/`

**Filled in its own run.** The dual-signal join (the robustness fallback; live-label is primary): the
camera's swap-proof `global_episode_seq` as the ordering spine + the fob `episode_ordinal` as the
label source, a clock-independent DURATION guardrail, and named failure tiebreaks (`ordinal_slip` /
`board_swap` / `clock_suspect` / `needs_review`). Pairs left+right by the shared `episode_id`. Deletes
are void-by-flag with `global_episode_seq`-gap detection. (CONTRACT §3.6.)
