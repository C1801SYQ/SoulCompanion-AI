"""Command-line maintenance for one local child's emotion database."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from core.data_admin import DataAdmin, DataAdminError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local emotion storage maintenance. Backups contain raw private data.")
    parser.add_argument("--db", default=config.DATABASE_PATH, help="Existing source SQLite database")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info", help="Show schema, counts and manual retention policy")
    backup = commands.add_parser("backup", help="Create a verified SQLite backup; output must not exist")
    backup.add_argument("--output", required=True)
    export = commands.add_parser("export", help="Export JSON/CSV without raw text by default")
    export.add_argument("--output", required=True)
    export.add_argument("--include-raw", action="store_true", help="Explicitly include private speech/context")
    delete = commands.add_parser("delete", help="Delete both emotion records and legacy logs after a verified backup")
    delete.add_argument("--backup", required=True)
    delete.add_argument("--confirm-delete", action="store_true")
    retention = commands.add_parser("retention", help="Manually delete records older than the configured number of days; 0 disables deletion")
    retention.add_argument("--days", type=int, default=config.RETENTION_DAYS)
    retention.add_argument("--backup")
    retention.add_argument("--confirm-delete", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if config.DEMO_MODE:
        parser.error("Real database maintenance is disabled in demo mode")
    try:
        admin = DataAdmin(args.db)
        if args.command == "info":
            result = admin.info()
        elif args.command == "backup":
            result = admin.backup(args.output)
        elif args.command == "export":
            result = admin.export(args.output, include_raw=args.include_raw)
        elif args.command == "delete":
            result = admin.delete(args.backup, confirm_delete=args.confirm_delete)
        else:
            result = admin.retention(args.days, args.backup, confirm_delete=args.confirm_delete)
    except (DataAdminError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"Maintenance failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
