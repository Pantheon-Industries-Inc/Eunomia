"""eunomia-qc CLI — run QC checks, grade episodes, summarize verdicts."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from eunomia_qc.engine import grade_episode, run_checks_for_date
from eunomia_qc.vlm import make_vlm_client


def _make_conn():
    """Create a database connection from environment."""
    from eunomia_edge_store.config import StoreConfig
    from eunomia_edge_store.engine import make_engine

    config = StoreConfig.from_env()
    engine = make_engine(config, echo=False)
    return engine.connect()


def _run_checks(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    vlm = make_vlm_client()
    if vlm is None:
        logging.warning("OPENROUTER_API_KEY not set — VLM checks will be skipped")

    conn = _make_conn()
    try:
        results = asyncio.run(
            run_checks_for_date(conn, args.date, vlm, dry_run=args.dry_run)
        )
    finally:
        conn.close()

    if not results:
        print(f"No episodes found for {args.date}")
        return 0

    accept = sum(1 for r in results if r.verdict == "accept")
    review = sum(1 for r in results if r.verdict == "review")
    reject = sum(1 for r in results if r.verdict == "reject")
    print(f"\n{'DRY RUN — ' if args.dry_run else ''}QC results for {args.date}:")
    print(f"  Episodes: {len(results)}")
    print(f"  Accept:   {accept}")
    print(f"  Review:   {review}")
    print(f"  Reject:   {reject}")

    for r in results:
        marker = {"accept": "✓", "review": "?", "reject": "✗"}.get(r.verdict, " ")
        print(
            f"  [{marker}] {r.episode_id}: {r.verdict} (score={r.score}) — {r.verdict_reason}"
        )

    return 0


def _grade(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    vlm = make_vlm_client()
    if vlm is None:
        logging.warning("OPENROUTER_API_KEY not set — VLM checks will be skipped")

    from eunomia_edge_store import store

    conn = _make_conn()
    try:
        episode = store.get(conn, "episode", episode_id=args.episode_id)
        if not episode:
            print(f"Episode not found: {args.episode_id}")
            return 1

        result = asyncio.run(grade_episode(conn, episode, vlm, dry_run=args.dry_run))
    finally:
        conn.close()

    if result is None:
        print("QC grading failed (cost budget exceeded?)")
        return 1

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}QC result for {result.episode_id}:")
    print(f"  Verdict: {result.verdict}")
    print(f"  Score:   {result.score}")
    print(f"  Reason:  {result.verdict_reason}")
    print("  Checks:")
    for c in result.checks:
        marker = {"pass": "✓", "fail": "✗", "na": "-", "skipped": "⊘"}.get(
            c.status, " "
        )
        nn = " [NON-NEG]" if c.non_negotiable and c.status == "fail" else ""
        print(f"    [{marker}] {c.id} {c.name}: {c.status}{nn}")
        if c.how:
            print(f"        How: {c.how}")
        if c.why:
            print(f"        Why: {c.why}")

    return 0


def _summary(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    import sqlalchemy as sa

    from eunomia_edge_store import schema

    from datetime import datetime, timedelta

    start = datetime.fromisoformat(f"{args.date}T00:00:00+00:00")
    end = start + timedelta(days=1)

    conn = _make_conn()
    try:
        oe = schema.TABLES["operational_event"]
        rows = (
            conn.execute(
                sa.select(oe.c.payload)
                .where(oe.c.event_type == "qa_verdict")
                .where(oe.c.as_of >= start, oe.c.as_of < end)
            )
            .mappings()
            .all()
        )
    finally:
        conn.close()

    if not rows:
        print(f"No QC verdicts found for {args.date}")
        return 0

    verdicts = [r["payload"].get("verdict", "unknown") for r in rows]
    accept = verdicts.count("accept")
    review = verdicts.count("review")
    reject = verdicts.count("reject")
    print(f"QC summary for {args.date}:")
    print(f"  Total:  {len(verdicts)}")
    print(f"  Accept: {accept}")
    print(f"  Review: {review}")
    print(f"  Reject: {reject}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="eunomia-qc", description="Eunomia QC engine")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run-checks", help="Run QC checks on episodes for a date")
    run.add_argument("date", help="Date in YYYY-MM-DD format")
    run.add_argument(
        "--dry-run", action="store_true", help="Parse and check without writing to DB"
    )

    grd = sub.add_parser("grade", help="Grade a single episode")
    grd.add_argument("episode_id", help="Episode ID to grade")
    grd.add_argument(
        "--dry-run", action="store_true", help="Check without writing to DB"
    )

    smry = sub.add_parser("summary", help="Print verdict summary for a date")
    smry.add_argument("date", help="Date in YYYY-MM-DD format")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(2)

    handlers = {
        "run-checks": _run_checks,
        "grade": _grade,
        "summary": _summary,
    }
    sys.exit(handlers[args.command](args))
