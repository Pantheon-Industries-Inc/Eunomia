"""CLI entry point for the normalize pipeline.

One subcommand: ``run``, with ``--dry-run``, ``--force``, and optional ``--dsn``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from eunomia_normalize.convert import load_intrinsics, normalize_video
from eunomia_normalize.discover import DiscoverResult, discover

log = logging.getLogger(__name__)

NORMALIZED_TIER = "normalized"


def _update_footage_reference(dsn: str, episode_id: str, normalized_path: Path) -> None:
    """Append the normalized path to footage_reference.locations in S1."""
    from eunomia_edge_store.config import StoreConfig
    from eunomia_edge_store.engine import make_engine
    from eunomia_edge_store import store

    cfg = StoreConfig(dsn=dsn)
    engine = make_engine(cfg)

    location = f"{NORMALIZED_TIER}:{normalized_path}"

    with engine.begin() as conn:
        ref = store.get(conn, "footage_reference", episode_id=episode_id)
        if ref is None:
            log.warning(
                "No footage_reference for episode %s — skipping S1 update",
                episode_id,
            )
            return

        locations: list[str] = ref.get("locations") or []
        if location not in locations:
            locations.append(location)
            store.upsert(
                conn,
                "footage_reference",
                {"episode_id": episode_id, "locations": locations},
            )
            log.info("Updated footage_reference for %s", episode_id)


def _print_summary(result: DiscoverResult, converted: int) -> None:
    lines = [
        f"candidates found:      {len(result.candidates)}",
        f"already normalized:    {len(result.already_normalized)}",
        f"no footage:            {len(result.no_footage)}",
        f"converted:             {converted}",
    ]
    print("\n".join(lines))


def _cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    intrinsics = load_intrinsics(Path(args.intrinsics) if args.intrinsics else None)
    result = discover(root, force=args.force)

    if args.dry_run:
        print("--- dry run (no writes) ---")
        for c in result.candidates:
            print(f"  would convert: {c.footage_path}")
        _print_summary(result, 0)
        return 0

    converted = 0
    errors = 0
    for c in result.candidates:
        try:
            out = normalize_video(c.footage_path, c.output_dir, intrinsics)
            converted += 1

            if args.dsn and c.episode_id:
                try:
                    _update_footage_reference(args.dsn, c.episode_id, out)
                except Exception:
                    log.exception("Failed to update S1 for episode %s", c.episode_id)
        except Exception:
            log.exception("Failed to normalize %s", c.footage_path)
            errors += 1

    _print_summary(result, converted)
    if errors:
        print(f"errors:                {errors}")
    return 1 if errors else 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="eunomia-normalize",
        description="Eunomia video normalization — Insta360 X3 SBS fisheye → flat perspective MP4.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser(
        "run",
        help="Scan drain output, convert .insv files to flat perspective MP4.",
    )
    run.add_argument("path", help="Path to the drain output root directory")
    run.add_argument(
        "--dsn",
        default=None,
        help="S1 Postgres DSN. When set, updates footage_reference.locations.",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be converted without writing files or DB.",
    )
    run.add_argument(
        "--force",
        action="store_true",
        help="Re-convert even if normalized output already exists.",
    )
    run.add_argument(
        "--intrinsics",
        default=None,
        help="Path to camera_intrinsics.json (default: shipped config).",
    )

    args = parser.parse_args()
    if args.command == "run":
        code = _cmd_run(args)
    else:
        parser.print_help()
        code = 2
    raise SystemExit(code)
