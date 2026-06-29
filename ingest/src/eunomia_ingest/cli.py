"""CLI entry points for the ingest pipeline.

Two subcommands: ``scan-drain`` and ``import-fob-log``, both with ``--dry-run``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eunomia_ingest.fob_log import parse_fob_log
from eunomia_ingest.ingest import IngestReport, ingest_drain, ingest_fob_log
from eunomia_ingest.sidecar import scan_drain


def _print_report(report: IngestReport) -> None:
    lines = []
    if report.sidecars_processed or report.sidecars_skipped:
        lines.append(f"sidecars processed:  {report.sidecars_processed}")
        lines.append(f"sidecars skipped:    {report.sidecars_skipped}")
    if report.episodes_created:
        lines.append(f"episodes created:    {report.episodes_created}")
    if report.episodes_enriched:
        lines.append(f"episodes enriched:   {report.episodes_enriched}")
    if report.events_appended:
        lines.append(f"events appended:     {report.events_appended}")
    if report.sessions_created:
        lines.append(f"sessions created:    {report.sessions_created}")
    if report.footage_refs_created:
        lines.append(f"footage refs:        {report.footage_refs_created}")
    if report.footage_orphans:
        lines.append(f"footage orphans:     {report.footage_orphans}")
    if report.sidecar_orphans:
        lines.append(f"sidecar orphans:     {report.sidecar_orphans}")
    if report.fob_log_lines:
        lines.append(f"fob log lines:       {report.fob_log_lines}")
        lines.append(f"fob log skipped:     {report.fob_log_skipped}")
        lines.append(f"fob log errors:      {report.fob_log_errors}")
    if report.anomalies:
        lines.append(f"anomalies:           {len(report.anomalies)}")
        for a in report.anomalies:
            lines.append(f"  [{a.anomaly_type}] {a.detail}")
    print("\n".join(lines))


def _cmd_scan_drain(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    if args.dry_run:
        scan = scan_drain(root)
        report = IngestReport(
            sidecars_processed=len(scan.records),
            sidecars_skipped=len(scan.skipped),
            footage_orphans=len(scan.footage_orphans),
            sidecar_orphans=sum(1 for r in scan.records if not r.footage_exists),
        )
        print("--- dry run (no writes) ---")
        _print_report(report)
        return 0

    from eunomia_edge_store.config import StoreConfig
    from eunomia_edge_store.engine import make_engine

    cfg = StoreConfig.from_env()
    engine = make_engine(cfg)
    with engine.begin() as conn:
        report = ingest_drain(root, conn)

    _print_report(report)
    return 1 if report.sidecars_skipped else 0


def _cmd_import_fob_log(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"error: {path} is not a file", file=sys.stderr)
        return 2

    if args.dry_run:
        log = parse_fob_log(path)
        report = IngestReport(
            fob_log_lines=(
                len(log.ordinals)
                + len(log.episode_starts)
                + len(log.episode_stops)
                + len(log.episode_discards)
                + len(log.session_signins)
                + len(log.assignments)
                + len(log.skipped_lines)
                + len(log.parse_errors)
            ),
            fob_log_skipped=len(log.skipped_lines),
            fob_log_errors=len(log.parse_errors),
        )
        print("--- dry run (no writes) ---")
        _print_report(report)
        return 0

    from eunomia_edge_store.config import StoreConfig
    from eunomia_edge_store.engine import make_engine

    cfg = StoreConfig.from_env()
    engine = make_engine(cfg)
    with engine.begin() as conn:
        report = ingest_fob_log(path, conn, kit_id=args.kit_id)

    _print_report(report)
    return 1 if report.fob_log_errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="eunomia-ingest",
        description="Eunomia ingest pipeline — camera sidecars + fob logs → S1 store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    drain = sub.add_parser(
        "scan-drain",
        help="Scan drain output for sidecars, write episodes + footage refs to S1.",
    )
    drain.add_argument("path", help="Path to the drain output root directory")
    drain.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing to S1",
    )

    fob = sub.add_parser(
        "import-fob-log",
        help="Parse a fob JSONL log, write events + sessions to S1.",
    )
    fob.add_argument("path", help="Path to the JSONL dump file")
    fob.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing to S1",
    )
    fob.add_argument(
        "--kit-id",
        default=None,
        help="Override kit_id (use when the log doesn't self-identify)",
    )

    args = parser.parse_args()
    if args.command == "scan-drain":
        code = _cmd_scan_drain(args)
    elif args.command == "import-fob-log":
        code = _cmd_import_fob_log(args)
    else:
        parser.print_help()
        code = 2
    raise SystemExit(code)
