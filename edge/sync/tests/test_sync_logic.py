"""Pure logic tests for SYNC1 — no DB, no network.

Tests the episode selection, state machine, rsync command construction, and sweep logic
that the shell scripts implement. These validate the DESIGN; the scripts themselves are
integration-tested manually (--dry-run, --check).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


# ── Episode selection logic ──────────────────────────────────────────────────


@dataclass(frozen=True)
class FootageRef:
    episode_id: str
    footage_state: str
    spot_check_selected: bool = False
    locations: tuple[str, ...] = ()


def select_episodes(refs: list[FootageRef]) -> list[FootageRef]:
    """Replicate the SQL ORDER BY from eunomia-sync-footage.sh:
    spot_check_selected DESC NULLS LAST, episode_id DESC.
    Only episodes with footage_state = 'on_styx' are eligible.
    """
    eligible = [r for r in refs if r.footage_state == "on_styx"]
    return sorted(
        eligible,
        key=lambda r: (r.spot_check_selected, r.episode_id),
        reverse=True,
    )


class TestEpisodeSelection:
    def test_only_on_styx_selected(self) -> None:
        refs = [
            FootageRef("ep-1", "on_card"),
            FootageRef("ep-2", "on_styx"),
            FootageRef("ep-3", "shipped"),
            FootageRef("ep-4", "on_hades"),
            FootageRef("ep-5", "purged"),
            FootageRef("ep-6", "on_styx"),
        ]
        result = select_episodes(refs)
        assert [r.episode_id for r in result] == ["ep-6", "ep-2"]

    def test_spot_check_first(self) -> None:
        refs = [
            FootageRef("ep-a", "on_styx", spot_check_selected=False),
            FootageRef("ep-b", "on_styx", spot_check_selected=True),
            FootageRef("ep-c", "on_styx", spot_check_selected=False),
        ]
        result = select_episodes(refs)
        assert result[0].episode_id == "ep-b"
        assert result[0].spot_check_selected is True

    def test_newest_first_within_group(self) -> None:
        refs = [
            FootageRef("ep-001", "on_styx"),
            FootageRef("ep-003", "on_styx"),
            FootageRef("ep-002", "on_styx"),
        ]
        result = select_episodes(refs)
        assert [r.episode_id for r in result] == ["ep-003", "ep-002", "ep-001"]

    def test_empty_input(self) -> None:
        assert select_episodes([]) == []

    def test_no_eligible(self) -> None:
        refs = [
            FootageRef("ep-1", "on_hades"),
            FootageRef("ep-2", "shipped"),
        ]
        assert select_episodes(refs) == []


# ── State machine ────────────────────────────────────────────────────────────

VALID_TRANSITIONS = {
    "on_card": {"on_styx"},
    "on_styx": {"shipped"},
    "shipped": {"on_hades", "on_styx"},  # on_styx = revert on validation failure
    "on_hades": {"purged"},
    "purged": set(),
}
STATES_ORDER = ["on_card", "on_styx", "shipped", "on_hades", "purged"]


def is_valid_transition(from_state: str, to_state: str) -> bool:
    return to_state in VALID_TRANSITIONS.get(from_state, set())


class TestStateMachine:
    def test_forward_transitions(self) -> None:
        for i in range(len(STATES_ORDER) - 1):
            assert is_valid_transition(STATES_ORDER[i], STATES_ORDER[i + 1])

    def test_cannot_skip(self) -> None:
        assert not is_valid_transition("on_card", "shipped")
        assert not is_valid_transition("on_styx", "on_hades")
        assert not is_valid_transition("on_card", "on_hades")

    def test_cannot_reverse(self) -> None:
        assert not is_valid_transition("on_hades", "shipped")
        assert not is_valid_transition("shipped", "on_card")
        assert not is_valid_transition("purged", "on_hades")

    def test_shipped_can_revert_to_on_styx(self) -> None:
        assert is_valid_transition("shipped", "on_styx")

    def test_purged_is_terminal(self) -> None:
        for state in STATES_ORDER:
            if state != "on_hades":
                assert not is_valid_transition("purged", state)


# ── Rsync command construction ───────────────────────────────────────────────


def build_rsync_cmd(
    remote: str,
    source_root: str,
    relpath: str,
    dest: str,
    ssh_key: str,
    bw_limit: int = 50000,
) -> list[str]:
    """Build the rsync command the sync script would run."""
    return [
        "rsync",
        "-ahz",
        "--partial",
        f"--bwlimit={bw_limit}",
        "--timeout=300",
        "--contimeout=30",
        "--skip-compress=insv/mp4/lrv/insp",
        "-e",
        f"ssh -i {ssh_key} -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new -o BatchMode=yes",
        f"{remote}:{source_root}/{relpath}/",
        f"{dest}/",
    ]


class TestRsyncCommand:
    def test_bwlimit_injected(self) -> None:
        cmd = build_rsync_cmd(
            "user@host", "/src", "ep1", "/dst", "/key", bw_limit=25000
        )
        assert "--bwlimit=25000" in cmd

    def test_default_bwlimit(self) -> None:
        cmd = build_rsync_cmd("user@host", "/src", "ep1", "/dst", "/key")
        assert "--bwlimit=50000" in cmd

    def test_ssh_key_in_command(self) -> None:
        cmd = build_rsync_cmd(
            "user@host", "/src", "ep1", "/dst", "/home/pluto/.ssh/key"
        )
        ssh_e = [c for c in cmd if c.startswith("ssh -i")][0]
        assert "/home/pluto/.ssh/key" in ssh_e

    def test_source_trailing_slash(self) -> None:
        cmd = build_rsync_cmd("user@host", "/src", "ep1", "/dst", "/key")
        source_arg = [c for c in cmd if c.startswith("user@host:")][0]
        assert source_arg.endswith("/")

    def test_dest_trailing_slash(self) -> None:
        cmd = build_rsync_cmd("user@host", "/src", "ep1", "/dst", "/key")
        assert cmd[-1].endswith("/")

    def test_skip_compress_video(self) -> None:
        cmd = build_rsync_cmd("user@host", "/src", "ep1", "/dst", "/key")
        assert "--skip-compress=insv/mp4/lrv/insp" in cmd

    def test_no_delete_flag(self) -> None:
        cmd = build_rsync_cmd("user@host", "/src", "ep1", "/dst", "/key")
        for arg in cmd:
            assert "--delete" not in arg


# ── Location parsing ─────────────────────────────────────────────────────────


def parse_styx_location(locations: list[str]) -> str | None:
    """Extract the relative path from a styx: location string."""
    for loc in locations:
        if loc.startswith("styx:"):
            return loc[len("styx:") :]
    return None


class TestLocationParsing:
    def test_styx_location(self) -> None:
        locs = ["styx:/kit01/DCIM/100_INSTA", "hades:/archive/kit01"]
        assert parse_styx_location(locs) == "/kit01/DCIM/100_INSTA"

    def test_no_styx_location(self) -> None:
        locs = ["hades:/archive/kit01"]
        assert parse_styx_location(locs) is None

    def test_empty(self) -> None:
        assert parse_styx_location([]) is None


# ── Broken-episode sweep logic ──────────────────────────────────────────────


class TestSweepLogic:
    def test_stale_tmp_identified(self, tmp_path: Path) -> None:
        dest = tmp_path / "umi"
        dest.mkdir()
        stale = dest / ".tmp-ep-stale"
        stale.mkdir()
        (stale / "file.mp4").touch()
        # Set mtime to 2 hours ago.
        old_time = time.time() - 7200
        os.utime(stale, (old_time, old_time))

        fresh = dest / ".tmp-ep-fresh"
        fresh.mkdir()
        (fresh / "file.mp4").touch()

        stale_age_secs = 3600
        now = time.time()

        stale_dirs = []
        for d in dest.iterdir():
            if d.is_dir() and d.name.startswith(".tmp-"):
                age = now - d.stat().st_mtime
                if age > stale_age_secs:
                    stale_dirs.append(d.name)

        assert ".tmp-ep-stale" in stale_dirs
        assert ".tmp-ep-fresh" not in stale_dirs

    def test_old_broken_purged(self, tmp_path: Path) -> None:
        broken = tmp_path / ".broken" / "stale_transfer"
        broken.mkdir(parents=True)

        old_ep = broken / "ep-old"
        old_ep.mkdir()
        old_time = time.time() - 8 * 86400  # 8 days ago
        os.utime(old_ep, (old_time, old_time))

        recent_ep = broken / "ep-recent"
        recent_ep.mkdir()

        purge_days = 7
        cutoff = time.time() - purge_days * 86400

        to_purge = []
        for ep_dir in broken.iterdir():
            if ep_dir.is_dir() and ep_dir.stat().st_mtime < cutoff:
                to_purge.append(ep_dir.name)

        assert "ep-old" in to_purge
        assert "ep-recent" not in to_purge

    def test_empty_broken_dir(self, tmp_path: Path) -> None:
        broken = tmp_path / ".broken"
        broken.mkdir()
        # Should not crash on empty broken dir.
        count = sum(1 for _ in broken.rglob("*") if _.is_dir())
        assert count == 0


# ── Status JSON generation ───────────────────────────────────────────────────


class TestStatusJson:
    def test_well_formed(self, tmp_path: Path) -> None:
        last_run = {
            "timestamp": "2026-06-29T12:00:00+00:00",
            "episodes_synced": 5,
            "episodes_failed": 1,
            "bytes_transferred": 1000000000,
            "episodes_pending": 3,
        }
        run_file = tmp_path / ".last_run.json"
        run_file.write_text(json.dumps(last_run))

        data = json.loads(run_file.read_text())
        assert data["episodes_synced"] == 5
        assert data["episodes_failed"] == 1
        assert data["bytes_transferred"] == 1_000_000_000
        assert data["episodes_pending"] == 3

    def test_missing_run_file(self, tmp_path: Path) -> None:
        run_file = tmp_path / ".last_run.json"
        assert not run_file.exists()


# ── Event ID determinism ────────────────────────────────────────────────────


class TestEventIdDeterminism:
    def test_same_input_same_id(self) -> None:
        ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        id1 = uuid.uuid5(ns, "sync:ep-123:sync_state_transition_on_hades")
        id2 = uuid.uuid5(ns, "sync:ep-123:sync_state_transition_on_hades")
        assert id1 == id2

    def test_different_episode_different_id(self) -> None:
        ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        id1 = uuid.uuid5(ns, "sync:ep-123:sync_state_transition_on_hades")
        id2 = uuid.uuid5(ns, "sync:ep-456:sync_state_transition_on_hades")
        assert id1 != id2

    def test_different_state_different_id(self) -> None:
        ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        id1 = uuid.uuid5(ns, "sync:ep-123:sync_state_transition_shipped")
        id2 = uuid.uuid5(ns, "sync:ep-123:sync_state_transition_on_hades")
        assert id1 != id2
