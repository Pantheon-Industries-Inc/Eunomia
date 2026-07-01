"""Infrastructure health data readers — filesystem-based, no database.

Reads SD card status JSON, camera map, SYNC1 status, and system health
from the local filesystem. All readers return ``None`` on missing/corrupt input.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_sd_card_status(ingest_root: Path) -> dict[str, Any] | None:
    path = ingest_root / "storage-health" / "sd-card-styx-status.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_camera_map(ingest_root: Path) -> dict[str, Any] | None:
    path = ingest_root / "config" / "camera_map.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_sync_status(status_path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(status_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def system_health() -> dict[str, Any]:
    mounts_env = os.environ.get("EUNOMIA_INFRA_MOUNTS", "/,/mnt/robot-pool/umi")
    mount_paths = [m.strip() for m in mounts_env.split(",") if m.strip()]

    disks: list[dict[str, Any]] = []
    for mount in mount_paths:
        try:
            usage = shutil.disk_usage(mount)
            disks.append(
                {
                    "mount": mount,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                    "pct": round(usage.used / usage.total * 100, 1)
                    if usage.total
                    else 0,
                }
            )
        except OSError:
            pass

    uptime_s = _read_uptime()
    load_avg = _read_load_avg()

    return {
        "disks": disks,
        "uptime_s": uptime_s,
        "uptime_formatted": format_uptime(uptime_s),
        "load_avg": load_avg,
    }


def _read_uptime() -> int | None:
    if platform.system() == "Linux":
        try:
            return int(float(Path("/proc/uptime").read_text().split()[0]))
        except (OSError, ValueError, IndexError):
            pass
    try:
        out = subprocess.run(
            ["uptime"], capture_output=True, text=True, timeout=5
        ).stdout
        if "up" in out:
            return _parse_uptime_output(out)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _parse_uptime_output(text: str) -> int | None:
    try:
        after_up = text.split("up", 1)[1].split(",")[0].strip()
        parts = after_up.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 3600 + int(parts[1]) * 60
        if "day" in after_up:
            days = int(after_up.split("day")[0].strip())
            return days * 86400
    except (ValueError, IndexError):
        pass
    return None


def _read_load_avg() -> list[float]:
    if platform.system() == "Linux":
        try:
            parts = Path("/proc/loadavg").read_text().split()
            return [float(parts[0]), float(parts[1]), float(parts[2])]
        except (OSError, ValueError, IndexError):
            pass
    try:
        load = os.getloadavg()
        return [round(load[0], 2), round(load[1], 2), round(load[2], 2)]
    except OSError:
        return []


def card_summary(status: dict[str, Any]) -> dict[str, int]:
    slots = status.get("slots", [])
    counts: Counter[str] = Counter()
    for slot in slots:
        counts["total"] += 1
        if slot.get("hardware_present"):
            counts["present"] += 1
        latest = slot.get("latest_status", "")
        if latest == "copying":
            counts["ingesting"] += 1
        elif latest in ("styx-verified", "drained-done"):
            counts["drained"] += 1
        elif latest.startswith("error"):
            counts["error"] += 1
        elif latest == "" or latest == "idle":
            counts["idle"] += 1
    return dict(counts)


def status_freshness(status: dict[str, Any]) -> dict[str, Any]:
    generated_at = status.get("generated_at", "")
    if not generated_at:
        return {"generated_at": "", "age_seconds": -1, "stale": True}
    try:
        ts = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        age = (datetime.now(UTC) - ts).total_seconds()
        return {
            "generated_at": generated_at,
            "age_seconds": int(age),
            "stale": age > 30,
        }
    except (ValueError, TypeError):
        return {"generated_at": generated_at, "age_seconds": -1, "stale": True}


def camera_map_warnings(camera_map: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    op_sides: dict[str, list[str]] = {}
    seen_pairs: dict[tuple[str, str], list[str]] = {}

    for serial, entry in camera_map.items():
        if not isinstance(entry, dict):
            continue
        if not entry.get("active", True):
            continue
        operator = entry.get("operator", "")
        side = entry.get("side", "")
        if not operator or not side:
            warnings.append(
                {
                    "type": "unassigned",
                    "detail": f"Camera {serial[:8]}… has no operator/side assignment",
                }
            )
            continue

        pair = (operator, side)
        seen_pairs.setdefault(pair, []).append(serial)
        op_sides.setdefault(operator, []).append(side)

    for pair, serials in seen_pairs.items():
        if len(serials) > 1:
            short = [s[:8] for s in serials]
            warnings.append(
                {
                    "type": "duplicate",
                    "detail": f"{pair[0]}/{pair[1]} assigned to {len(serials)} cameras: {', '.join(short)}…",
                }
            )

    for operator, sides in op_sides.items():
        unique = set(sides)
        if unique == {"left"} or unique == {"right"}:
            warnings.append(
                {
                    "type": "one_side",
                    "detail": f"{operator} only has {next(iter(unique))} camera assigned",
                }
            )

    return warnings


def save_camera_map(ingest_root: Path, data: dict[str, Any]) -> None:
    map_file = ingest_root / "config" / "camera_map.json"
    bak_file = map_file.with_suffix(".json.bak")
    tmp_file = map_file.with_suffix(".json.tmp")

    map_file.parent.mkdir(parents=True, exist_ok=True)

    if map_file.exists():
        shutil.copy2(map_file, bak_file)

    tmp_file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp_file.rename(map_file)


def active_ingest_count(status: dict[str, Any]) -> int:
    return sum(
        1 for slot in status.get("slots", []) if slot.get("latest_status") == "copying"
    )


def format_uptime(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
