# Run I1 — `ingest/`: the ingest pipeline (plan-of-record)

Read from: the merged firmware formats (F9 `operational_record.h`, F2 `sidecar_assembly.h`), the S1
store (`edge/store/`), the operational contracts (`contracts/operational/`), `docs/CONTRACT.md`,
`docs/SPEC.md`, `docs/MODULE_MAP.md`, and the existing `ingest/` README skeleton. Victor's styx-ingest
reference (`/tmp/styx_ingest/`) was not available; drain output layout inferred from CONTRACT §2.1,
SPEC §1.7, and the substrate README.

## What I1 is (and is NOT)

- **IS:** the first real code under `ingest/` — the two parsers (camera sidecar + fob JSONL log), the
  episode_id join, the S1 write path, deterministic event_id minting (idempotent re-import), anomaly
  flagging, and a CLI for operators. Gets the raw data from the two on-site sources into S1's
  `operational_event`, `episode`, and `session` tables.
- **IS NOT:** identity resolution (crosswalk, serial retargeting, kit aliases — that's `identity/`, a
  later run). IS NOT the dual-signal ordinal join with tiebreaks (`join/`). IS NOT QC (`qc/`). IS NOT
  the release record (`release/`). IS NOT the parallel orchestrator (`orchestrator/`).
- **IS NOT:** a contract change. `contracts/_generated/` stays byte-identical. No firmware changes.

I1 builds the **foundation layer** that the later ingest submodules (`identity/`, `join/`, `qc/`,
`release/`, `orchestrator/`) compose on top of. The parsers, the S1 write path, and the idempotency
strategy are shared infrastructure.

## 1. Package shape

A new uv workspace member `ingest/` (`eunomia-ingest`), src-layout, mirroring `edge/store/`.

```
ingest/
  pyproject.toml                        # eunomia-ingest; deps below
  README.md                             # already exists (0a skeleton)
  identity/README.md                    # already exists (future run)
  join/README.md                        # already exists (future run)
  qc/README.md                          # already exists (future run)
  release/README.md                     # already exists (future run)
  orchestrator/README.md                # already exists (future run)
  src/eunomia_ingest/
    __init__.py
    sidecar.py                          # sidecar JSON parser + contract validator
    fob_log.py                          # fob JSONL parser (dispatch by "T" type)
    events.py                           # deterministic event_id minting + event record construction
    ingest.py                           # the pipeline: scan drain → parse → join → write S1
    cli.py                              # CLI entry points (argparse, stdlib-only)
  tests/
    conftest.py
    test_sidecar.py                     # pure parser tests (no DB)
    test_fob_log.py                     # pure parser tests (no DB)
    test_events.py                      # idempotent event_id minting tests (no DB)
    test_ingest.py                      # DB-backed integration tests (skip without DSN)
    fixtures/
      drain_output/                     # synthetic drain tree (sidecars + dummy .insv refs)
      fob_dump.jsonl                    # synthetic fob log (all T types + edge cases)
```

### Dependencies

```toml
[project]
name = "eunomia-ingest"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = [
    "eunomia-contracts",
    "eunomia-edge-store",
]

[project.scripts]
eunomia-ingest = "eunomia_ingest.cli:main"

[tool.uv.sources]
eunomia-contracts = { workspace = true }
eunomia-edge-store = { workspace = true }
```

### Workspace integration

Root `pyproject.toml` changes:
- Add `"ingest"` to `[tool.uv.workspace] members`
- Add `"ingest"` to `[tool.pytest.ini_options] testpaths`
- Add `"eunomia_ingest"` to `[tool.importlinter] root_packages`
- Add import-linter contract: `eunomia_ingest` depends only on `eunomia_contracts` +
  `eunomia_edge_store` (forbidden: `eunomia_bench_harness`, `eunomia_consoles_provisioning`)
- Update existing contracts to list `eunomia_ingest` as forbidden where appropriate

## 2. Drain-scan logic (`sidecar.py` + `ingest.py`)

### Directory layout expectation

The drain output follows the structure from CONTRACT §2.1 and the substrate README. After
`verify-and-drain.sh` runs, the footage + sidecars live under a drain root:

```
<drain_root>/
  <kit_id>/                             # or <kit_id>-<card_id>/ — flexible
    DCIM/
      100_INSTA/                        # (or any numbered subdir — glob all)
        VID_<timestamp>_00_<seq>.insv   # footage (or .mp4 — glob both)
        VID_<timestamp>_<seq>.eunomia.json  # sidecar (binds by ts_seq composite)
        ...
    PANTHEON/                           # identity files (if present)
      pantheon_camera.env
      pantheon_fob.env
    .camera-serial                      # body serial stamp (if present)
```

### Discovery algorithm

1. Walk `<drain_root>` recursively, collect all `*.eunomia.json` files.
2. For each sidecar file:
   a. Parse JSON; validate against `eunomia-sidecar/v1` using the contract validator
      (`eunomia_contracts.sidecar.validate()`). Collect HARD errors and WARN warnings.
   b. If HARD errors: log the sidecar path + errors, skip (flag as anomaly), continue.
   c. Extract `files.back` → resolve the expected footage file path relative to the sidecar's
      directory. Check if the footage file exists.
   d. If footage missing: flag anomaly "sidecar with no matching footage" but still process the
      sidecar (the episode record is useful even without confirmed footage).
3. After processing all sidecars, scan for orphaned footage files (`*.insv`, `*.mp4`) that have no
   matching sidecar. Flag each as anomaly "footage without sidecar."
4. Optionally read PANTHEON identity files + `.camera-serial` if present (for camera_id cross-check
   against the sidecar's `identity.camera_id`).

### Sidecar → parsed record

`sidecar.py` exports a `parse_sidecar(path: Path) → SidecarRecord | None` function that returns a
typed dataclass (or None on HARD validation failure):

```python
@dataclass(frozen=True)
class SidecarRecord:
    # from sidecar JSON (field names match the contract)
    episode_id: str
    global_episode_seq: int
    seq: int
    kit_id: str
    side: str                           # "left" | "right"
    camera_id: str
    operator_id: str
    station_id: str
    task_id: str
    task_name: str
    session_id: str
    rotation_id: str
    prompt: str
    task_source: str
    episode_ordinal: int | None
    bimanual_episode_id: str | None
    display_id: str | None
    started_unix: float | None
    stopped_unix: float | None
    stop_reason: str | None
    archive: int                        # 0 or 1
    recording_suspect: int              # 0 or 1
    # provenance
    camera_firmware: str | None
    fob_id: str | None
    fob_build: str | None
    kit_version: str | None
    site_id: str | None
    modality: str | None
    # resolved at scan time
    sidecar_path: Path
    footage_path: Path | None           # None if footage file missing
    footage_exists: bool
    hard_errors: list[str]
    warnings: list[str]
```

## 3. Fob-log parser (`fob_log.py`)

### Input format

The fob's operational log is extracted via `cmd=dumplog` over USB serial. It produces a JSONL file
(one JSON object per line). The format is defined by F9's `operational_record.h`:

```
{"T":"O","o":1,"t":1700000000,"k":"kit_07","f":"fobA","s":"1a2b3c4d","e":"eid-123"}
{"T":"E","st":"start","o":2,"k":"kit_07","e":"eid-123","op":"op1","stn":"5","tid":"t1","tn":"Fold","rv":"r1","ts":"boot_config"}
{"T":"E","st":"stop","e":"eid-123","o":2,"r":"operator","a":0,"rs":0}
{"T":"S","st":"signin","sid":"sess_1","k":"kit_07","op":"op1","site":"mx_1","fob":"fobA","fob_sid":"1a2b3c4d"}
{"T":"A","stn":"5","tid":"t1","tn":"Fold","rv":"r1","ts":"boot_config","k":"kit_07"}
```

### Parser design

`fob_log.py` exports `parse_fob_log(path: Path) → FobLogResult`:

```python
@dataclass(frozen=True)
class OrdinalEntry:
    ordinal: int
    wallclock_unix: int
    kit_id: str
    fob_id: str
    fob_session_id: str
    episode_id: str

@dataclass(frozen=True)
class EpisodeStarted:
    ordinal: int
    kit_id: str
    episode_id: str
    operator_id: str
    station_id: str
    task_id: str
    task_name: str
    rotation_id: str
    task_source: str

@dataclass(frozen=True)
class EpisodeStopped:
    episode_id: str
    ordinal: int
    stop_reason: str
    archive: int
    recording_suspect: int

@dataclass(frozen=True)
class EpisodeDiscarded:
    episode_id: str
    ordinal: int

@dataclass(frozen=True)
class SessionSignin:
    session_id: str
    kit_id: str
    operator_id: str
    site_id: str
    fob_id: str
    fob_session_id: str

@dataclass(frozen=True)
class StationAssignment:
    station_id: str
    task_id: str
    task_name: str
    rotation_id: str
    task_source: str
    kit_id: str

@dataclass(frozen=True)
class FobLogResult:
    ordinals: list[OrdinalEntry]
    episode_starts: list[EpisodeStarted]
    episode_stops: list[EpisodeStopped]
    episode_discards: list[EpisodeDiscarded]
    session_signins: list[SessionSignin]
    assignments: list[StationAssignment]
    skipped_lines: list[tuple[int, str, str]]   # (line_no, raw_line, reason)
    parse_errors: list[tuple[int, str, str]]    # (line_no, raw_line, error)
```

### Dispatch rules

| `"T"` | `"st"` | Handler | Notes |
|--------|--------|---------|-------|
| `"O"` | — | → `OrdinalEntry` | The ordinal-join spine |
| `"E"` | `"start"` | → `EpisodeStarted` | |
| `"E"` | `"stop"` | → `EpisodeStopped` | |
| `"E"` | `"discard"` | → `EpisodeDiscarded` | |
| `"S"` | `"signin"` | → `SessionSignin` | |
| `"S"` | `"call"` | → skipped (LLAMAR, being removed in R1) | Graceful skip, logged |
| `"S"` | other | → skipped (unknown subtype) | Forward-compatible |
| `"A"` | — | → `StationAssignment` | |
| other | — | → skipped (unknown type) | Forward-compatible |
| (malformed JSON) | — | → `parse_errors` | Line number + raw line + error |

**Forward-compatibility:** unknown `"T"` values or unknown `"st"` subtypes are skipped with a
structured warning (line number, raw content, reason). Never raise on unknown types — the fob firmware
evolves faster than ingest.

**Malformed lines:** JSON parse failures, missing `"T"` field, or missing required fields for a known
type → `parse_errors`. Processing continues; the rest of the log is still valid.

## 4. Join logic (`ingest.py`)

### The join key

**`episode_id` (UUIDv4)** is the pairing key between the two sources. The camera writes it to the
sidecar; the fob writes it to the JSONL log. Both receive it from the coordinator at START time.

### Join procedure

1. **Index sidecars by episode_id**: `dict[str, SidecarRecord]` from the drain scan.
2. **Index fob log entries by episode_id**: group `EpisodeStarted`, `EpisodeStopped`,
   `EpisodeDiscarded`, and `OrdinalEntry` by their `episode_id`.
3. **Merge**:
   - **Both sources present** → full join: create episode from sidecar (timestamps, camera_id,
     footage path), enrich with fob start event (task_id, operator_id, station_id confirmed), link
     ordinal spine. This is the happy path.
   - **Sidecar only** (no matching fob log entries) → create episode from sidecar data alone. Leave
     enrichment fields empty where the sidecar doesn't carry them (but note: the sidecar already
     carries task_id, operator_id, station_id from the fob-at-capture-time — so these are populated).
     The ordinal spine link is missing. Flag: `anomaly: "sidecar_only"`.
   - **Fob log only** (no matching sidecar) → create operational events from the fob log. Create a
     "pending" episode with fob-side fields only (task_id, operator_id, station_id, ordinal) but no
     camera data (no global_episode_seq, no footage path, no timing). Flag:
     `anomaly: "fob_log_only"`. The sidecar may arrive in a later drain.

### Session handling

`SessionSignin` entries from the fob log create/update session records independently of the
episode join. A session record is written for every signin event, keyed by `session_id`.

### Assignment handling

`StationAssignment` entries from the fob log create `operational_event` records (event_type =
`station_task_assigned`) independently of the episode join.

## 5. Idempotency

### Deterministic `event_id` minting

`events.py` exports `mint_event_id(namespace: str, *parts: str) → str` that produces a stable UUID
from the event's natural key. Uses `uuid5` with a project-specific namespace UUID:

```python
EUNOMIA_NS = uuid.UUID("e8a1c3d0-4f2b-4e6a-9c0f-1a2b3c4d5e6f")   # fixed, never changes

def mint_event_id(*parts: str) -> str:
    return str(uuid.uuid5(EUNOMIA_NS, ":".join(parts)))
```

### Event ID construction per type

| Source | Event type | `event_id` construction | Dedup key |
|--------|-----------|-------------------------|-----------|
| Fob `"E","st":"start"` | `episode_started` | `mint("episode_started", episode_id)` | One start per episode |
| Fob `"E","st":"stop"` | `episode_stopped` | `mint("episode_stopped", episode_id)` | One stop per episode |
| Fob `"E","st":"discard"` | `episode_discarded` | `mint("episode_discarded", episode_id)` | One discard per episode |
| Fob `"S","st":"signin"` | `session_opened` | `mint("session_opened", session_id)` | One signin per session |
| Fob `"A"` | `station_task_assigned` | `mint("station_task_assigned", kit_id, station_id, task_id, rotation_id)` | One assignment per (kit, station, task, rotation) |

### Re-import behavior

- **`operational_event`**: `append_event()` uses `ON CONFLICT DO NOTHING` on `event_id` → re-importing
  the same fob log is a no-op (identical event_ids produce conflict, silently skipped).
- **`episode`**: `upsert()` uses `ON CONFLICT DO UPDATE` on `episode_id` → re-importing the same
  sidecar overwrites with identical data (idempotent). A second import with NEW data (e.g., the fob
  log enriching an existing sidecar-only episode) correctly updates the record.
- **`session`**: `upsert()` uses `ON CONFLICT DO UPDATE` on `session_id` → re-importing the same
  signin event overwrites with identical data (idempotent).

### The ordinal spine

Ordinal entries (`"T":"O"`) are de-duped on `(kit_id, fob_session_id, ordinal)`. They are NOT written
as operational_events — they are metadata linking episodes to fob sessions. The ordinal is stored in
the episode record as `episode_ordinal` (already a column on the episode table).

**Open question:** should ordinal entries get their own tracking table (for the full ordinal spine
across a fob session), or is storing `episode_ordinal` on the episode sufficient for I1? **Recommend:
episode_ordinal on the episode record is sufficient for I1.** The full ordinal spine with gap
detection is `join/` work (a later run).

## 6. S1 write path (`ingest.py` + `events.py`)

### Sidecar → S1 records

Each parsed sidecar writes **two** records:

**a. `episode` (upsert)**

| Episode column | Source |
|----------------|--------|
| `schema` | `"eunomia-episode/v1"` |
| `episode_id` | `sidecar.episode_id` |
| `display_id` | `sidecar.display_id` |
| `bimanual_episode_id` | `sidecar.bimanual_episode_id` |
| `episode_ordinal` | `sidecar.episode_ordinal` |
| `global_episode_seq` | `sidecar.global_episode_seq` |
| `kit_id` | `sidecar.kit_id` |
| `side` | `sidecar.side` |
| `person_id` | `sidecar.operator_id` (identity resolution refines later) |
| `session_id` | `sidecar.session_id` |
| `task_id` | `sidecar.task_id` |
| `rotation_id` | `sidecar.rotation_id` |
| `station_id` | `sidecar.station_id` |
| `recorded_at` | `datetime.fromtimestamp(sidecar.started_unix, tz=UTC).isoformat()` |
| `ingested_at` | current timestamp (set once at ingest time) |
| `archive` | `sidecar.archive` |
| `recording_suspect` | `sidecar.recording_suspect` |
| `paired` | `False` (set by `join/` later) |
| `void` | `False` |
| `needs_review` | `True` if anomalies detected, else `False` |

**b. `footage_reference` (upsert)**

| Column | Source |
|--------|--------|
| `schema` | `"eunomia-footage-reference/v1"` |
| `episode_id` | `sidecar.episode_id` |
| `footage_state` | `"on_styx"` (the card has been drained) |
| `locations` | `[str(sidecar.footage_path)]` if footage exists, else `[]` |

### Fob log → S1 records

**a. `EpisodeStarted` → `operational_event` (append) + `episode` enrichment (upsert)**

```python
event = {
    "schema": "eunomia-operational-event/v1",
    "event_id": mint_event_id("episode_started", entry.episode_id),
    "event_type": "episode_started",
    "entity": "episode",
    "entity_id": entry.episode_id,
    "as_of": wallclock_from_ordinal(entry),   # from matching ordinal entry, if available
    "payload": {
        "task_id": entry.task_id,
        "task_name": entry.task_name,
        "station_id": entry.station_id,
        "operator_id": entry.operator_id,
        "rotation_id": entry.rotation_id,
        "task_source": entry.task_source,
        "ordinal": entry.ordinal,
        "kit_id": entry.kit_id,
    },
}
```

Episode enrichment (upserted onto existing episode if sidecar was already processed):

| Episode column | Source |
|----------------|--------|
| `person_id` | `entry.operator_id` |
| `task_id` | `entry.task_id` |
| `station_id` | `entry.station_id` |
| `rotation_id` | `entry.rotation_id` |

**b. `EpisodeStopped` → `operational_event` (append)**

```python
event = {
    "event_id": mint_event_id("episode_stopped", entry.episode_id),
    "event_type": "episode_stopped",
    "entity": "episode",
    "entity_id": entry.episode_id,
    "payload": {
        "stop_reason": entry.stop_reason,
        "archive": entry.archive,
        "recording_suspect": entry.recording_suspect,
        "ordinal": entry.ordinal,
    },
}
```

**c. `EpisodeDiscarded` → `operational_event` (append)**

```python
event = {
    "event_id": mint_event_id("episode_discarded", entry.episode_id),
    "event_type": "episode_discarded",
    "entity": "episode",
    "entity_id": entry.episode_id,
    "payload": {"ordinal": entry.ordinal},
}
```

**d. `SessionSignin` → `operational_event` (append) + `session` (upsert)**

```python
event = {
    "event_id": mint_event_id("session_opened", entry.session_id),
    "event_type": "session_opened",
    "entity": "session",
    "entity_id": entry.session_id,
    "payload": {
        "kit_id": entry.kit_id,
        "operator_id": entry.operator_id,
        "site_id": entry.site_id,
        "fob_id": entry.fob_id,
        "fob_session_id": entry.fob_session_id,
    },
}
```

Session upsert:

| Session column | Source |
|----------------|--------|
| `schema` | `"eunomia-session/v1"` |
| `session_id` | `entry.session_id` |
| `person_id` | `entry.operator_id` |
| `kit_id` | `entry.kit_id` |
| `site_id` | `entry.site_id` |
| `fob_session_id` | `entry.fob_session_id` |
| `signed_in_at` | wallclock from matching ordinal or log context |

**e. `StationAssignment` → `operational_event` (append)**

```python
event = {
    "event_id": mint_event_id(
        "station_task_assigned",
        entry.kit_id, entry.station_id, entry.task_id, entry.rotation_id,
    ),
    "event_type": "station_task_assigned",
    "entity": "task_station_assignment",
    "entity_id": f"{entry.kit_id}:{entry.station_id}:{entry.task_id}",
    "payload": {
        "station_id": entry.station_id,
        "task_id": entry.task_id,
        "task_name": entry.task_name,
        "rotation_id": entry.rotation_id,
        "task_source": entry.task_source,
        "kit_id": entry.kit_id,
    },
}
```

### Transactional boundaries

Per-command granularity:
- **`scan-drain`**: one transaction per sidecar (episode + footage_reference atomically). A corrupt
  sidecar doesn't block processing of the rest of the drain output. At end of scan, write a summary
  report (count processed, anomalies found).
- **`import-fob-log`**: one transaction per logical unit (all events from one fob session, grouped by
  `fob_session_id`). Falls back to per-line on error (process what we can, flag what we can't).

## 7. Anomaly detection

The pipeline flags (does not reject) these anomalies. Each anomaly is logged to stderr and optionally
written as an `operational_event` with `event_type = "ingest_anomaly"`.

| Anomaly | Detection | Severity |
|---------|-----------|----------|
| **Sidecar HARD validation failure** | Contract validator returns HARD errors | ERROR — sidecar skipped |
| **Footage without sidecar** | `.insv`/`.mp4` file has no matching `*.eunomia.json` | WARN — footage catalogued but no episode |
| **Sidecar without footage** | Sidecar's `files.back` doesn't resolve to an existing file | WARN — episode created, footage_reference empty |
| **Sidecar only (no fob log)** | episode_id from sidecar has no matching fob log entries | INFO — expected if fob hasn't been dumped yet |
| **Fob log only (no sidecar)** | episode_id from fob log has no matching sidecar | INFO — expected if card hasn't been drained yet |
| **camera_id mismatch** | Sidecar `identity.camera_id` doesn't match PANTHEON env or S1 `hardware_unit` | WARN — needs review |
| **recording_suspect** | Sidecar `outcome.recording_suspect == 1` | WARN — coordinator couldn't confirm clip grew |
| **Duplicate episode_id from different kits** | Two sidecars with same episode_id but different kit_id | ERROR — needs human review |
| **Malformed fob log line** | JSON parse failure or missing required fields | WARN — line skipped, rest processed |
| **Unknown fob log type** | Unrecognized `"T"` value | INFO — forward-compatible skip |

### Anomaly report structure

```python
@dataclass
class IngestReport:
    sidecars_processed: int
    sidecars_skipped: int               # HARD validation failures
    episodes_created: int
    episodes_enriched: int              # fob log enriched existing sidecar episodes
    events_appended: int
    sessions_created: int
    footage_orphans: int                # footage without sidecar
    sidecar_orphans: int                # sidecar without footage
    fob_log_lines: int
    fob_log_skipped: int
    fob_log_errors: int
    anomalies: list[Anomaly]
```

The CLI prints this report to stdout at the end of each command.

## 8. CLI interface (`cli.py`)

Two subcommands, argparse (stdlib), no third-party CLI framework:

### `eunomia-ingest scan-drain`

```
usage: eunomia-ingest scan-drain [-h] [--dry-run] path

Scan a drain output directory for camera sidecars, parse them, and write
episode + footage_reference records to S1.

positional arguments:
  path          Path to the drain output root directory

options:
  --dry-run     Parse and validate without writing to S1 (print report only)
```

Requires `EUNOMIA_STORE_DSN` env var (unless `--dry-run`).

### `eunomia-ingest import-fob-log`

```
usage: eunomia-ingest import-fob-log [-h] [--dry-run] [--kit-id KIT_ID] path

Parse a fob JSONL log dump and write operational_event + session + episode
enrichment records to S1.

positional arguments:
  path          Path to the JSONL dump file

options:
  --dry-run     Parse and validate without writing to S1 (print report only)
  --kit-id ID   Override kit_id (use when the log doesn't self-identify)
```

Requires `EUNOMIA_STORE_DSN` env var (unless `--dry-run`).

### Design notes

- Both commands are **idempotent**: re-running with the same input produces the same S1 state.
- `--dry-run` is the default-safe mode for operators to preview what would be written. All parsing,
  validation, and anomaly detection runs; only the S1 writes are skipped.
- Exit codes: 0 = success (anomalies may exist but are INFO/WARN), 1 = errors (HARD validation
  failures, DB connection failures), 2 = argument errors.

## 9. Validation (tests)

### Pure-logic tests (no DB, default `make gates`)

**`test_sidecar.py`:**
- Parse a valid full sidecar fixture → all fields populated correctly
- Parse a minimal (HARD-only) sidecar fixture → optional fields are None
- Parse a sidecar with HARD validation errors → returns None + error list
- Parse a sidecar with WARN-only issues → returns record + warning list
- Sidecar discovery in a synthetic drain tree → correct count, correct paths
- Footage matching: sidecar with existing footage → `footage_exists = True`
- Footage matching: sidecar with missing footage → `footage_exists = False`, anomaly flagged
- Orphan footage detection: `.insv` file with no matching sidecar → flagged

**`test_fob_log.py`:**
- Parse a log with all known types → correct dispatch to typed records
- Parse a log with unknown `"T"` type → skipped with warning, not error
- Parse a log with unknown `"st"` subtype under `"S"` → skipped with warning
- Parse a log with `"S","st":"call"` → gracefully skipped (LLAMAR removal)
- Parse a log with malformed JSON line → error captured, rest of log processed
- Parse a log with missing required fields → error captured for that line
- Parse an empty log → empty result, no errors
- Line numbers tracked correctly in skip/error reports

**`test_events.py`:**
- `mint_event_id` is deterministic: same inputs → same output
- `mint_event_id` is distinct: different inputs → different output
- Event construction from each fob log entry type → correct `event_type`, `entity`, `entity_id`
- Re-minting the same event → identical `event_id` (idempotency proof)

### DB-backed integration tests (skip without `EUNOMIA_STORE_TEST_DSN`)

**`test_ingest.py` (marked `@pytest.mark.db`):**
- Scan a synthetic drain tree → episodes + footage_references written to S1
- Import a synthetic fob log → operational_events + sessions written to S1
- Re-import the same drain → no duplicate episodes (idempotent)
- Re-import the same fob log → no duplicate events (idempotent)
- Sidecar-first then fob-log → episode enriched with fob data
- Fob-log-first then sidecar → episode created with fob data, then updated with sidecar data
- Both sources for same episode_id → full join, all fields populated

### Test fixtures

Synthetic fixtures under `ingest/tests/fixtures/`:
- `drain_output/` — a minimal drain tree with 2-3 sidecars (one full, one minimal, one with HARD
  errors), corresponding dummy `.insv` files (empty files — we don't process video), and one orphan
  footage file.
- `fob_dump.jsonl` — a synthetic fob log with one of each known type, one unknown type, one malformed
  line, and one `"S","st":"call"` line.

Reuse the existing sidecar contract fixtures from
`contracts/conformance/fixtures/sidecar/valid/full.json` and `minimal.json` where possible.

## 10. Build sequence

Ordered by dependency. Each step must leave gates green.

| Step | What | Files | Notes |
|------|------|-------|-------|
| **a** | Package bootstrap | `ingest/pyproject.toml`, root `pyproject.toml` updates, `ingest/src/eunomia_ingest/__init__.py` | `uv sync --all-packages`, import-linter, testpaths. Gates green with empty package. |
| **b** | Sidecar parser | `sidecar.py`, `test_sidecar.py`, test fixtures under `fixtures/drain_output/` | Pure logic, no S1 dep. Contract validator used. |
| **c** | Fob log parser | `fob_log.py`, `test_fob_log.py`, `fixtures/fob_dump.jsonl` | Pure logic, no S1 dep. All dispatch rules + edge cases. |
| **d** | Event ID minter | `events.py`, `test_events.py` | Pure logic. Deterministic UUID5 minting + event record construction. |
| **e** | Pipeline + S1 writes | `ingest.py`, `test_ingest.py` (DB tests), `conftest.py` | Integrates parsers + S1 store. Needs `EUNOMIA_STORE_TEST_DSN` for DB tests. |
| **f** | CLI | `cli.py` | argparse wiring. Thin layer over `ingest.py`. |
| **g** | Gates + cleanup | — | Full `make gates` green. Verify `contracts/_generated` untouched. |

## Open questions (flagged, not silently decided)

1. **Drain directory layout flexibility.** The plan assumes `<drain_root>/<kit_id>/DCIM/100_INSTA/`
   but the actual layout depends on `verify-and-drain.sh` (not available for review). The scanner
   should use recursive glob (`**/*.eunomia.json`) rather than hardcoding a depth. **Confirm the
   actual drain output layout with Victor before implementing.**

2. **Ordinal spine storage.** I1 stores `episode_ordinal` on the episode record from the sidecar.
   The fob log's ordinal entry (`"T":"O"`) provides a richer spine (linking episode_id to
   fob_session_id + wallclock). Should I1 store ordinal entries in their own table, or is the
   episode-level `episode_ordinal` sufficient until `join/` lands? **Recommend: episode_ordinal is
   sufficient for I1; the ordinal spine table is `join/` scope.**

3. **`signed_in_at` for sessions.** The fob log's `"S","st":"signin"` doesn't carry a timestamp
   field. The wallclock comes from the corresponding ordinal entry (if one exists for that fob
   session). If no ordinal provides a wallclock, `signed_in_at` stays NULL. **Confirm this is
   acceptable or whether we should use the earliest ordinal's `"t"` field from the same
   `fob_session_id`.**

4. **`person_id` ↔ `operator_id` mapping.** The sidecar and fob log use `operator_id`; the S1
   episode and session tables use `person_id`. I1 stores `operator_id` directly into `person_id`
   (they are the same handle on-site). The `identity/` module will later refine this via roster
   lookup. **Confirm this direct mapping is acceptable for I1.**

5. **`task_version` resolution.** The sidecar and fob log carry `task_id` but not `task_version`.
   The episode table has `task_version` (WARN, nullable in store as `force_not_null`). I1 leaves
   `task_version` NULL; the `release/` module resolves it via as-of lookup against the task table.
   **Confirm NULL is acceptable for I1, or should I1 do the as-of resolution?**

6. **Anomaly storage.** Should anomalies be written as `operational_event` records with
   `event_type = "ingest_anomaly"`, or stored separately (log file, separate table)? **Recommend:
   `operational_event` with `event_type = "ingest_anomaly"` — keeps everything in the event log,
   queryable, and follows the existing append-only pattern. The `event_type` is an open string so
   this is additive.**
