"""CLI entrypoint for starloom."""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from . import config
from .database import Database
from .api.client import SpaceTrackClient
from .api.fetcher import Fetcher
from .render import render_frame


def _make_client() -> SpaceTrackClient:
    username = os.environ.get("SPACETRACK_USERNAME")
    password = os.environ.get("SPACETRACK_PASSWORD")
    if not username or not password:
        print("Error: Set SPACETRACK_USERNAME and SPACETRACK_PASSWORD in .env")
        sys.exit(1)
    return SpaceTrackClient(username=username, password=password)


def cmd_fetch(args: argparse.Namespace) -> None:
    client = _make_client()
    db = Database(args.db)

    try:
        client.login()
        fetcher = Fetcher(client, db)
        fetcher.run(
            start_date=args.start_date,
            end_date=args.end_date,
            dry_run=args.dry_run,
            bulk_dir=args.bulk_dir,
        )
    except KeyboardInterrupt:
        logging.info("Interrupted — progress has been saved")
    finally:
        db.close()
        client.close()


def cmd_status(args: argparse.Namespace) -> None:
    db = Database(args.db)
    sats = db.get_satellite_count()
    records = db.get_record_count()
    days = db.get_days_fetched_count()
    latest = db.get_latest_fetched_date()
    print(f"Database:           {args.db}")
    print(f"Satellites tracked: {sats:,}")
    print(f"GP history records: {records:,}")
    print(f"Days fetched (API): {days:,}")
    if latest:
        print(f"Latest fetch date:  {latest}")
    db.close()


def cmd_catalog(args: argparse.Namespace) -> None:
    client = _make_client()
    db = Database(args.db)
    try:
        client.login()
        catalog = client.fetch_starlink_catalog()
        db.upsert_satellites(catalog)
        print(f"Found {len(catalog)} Starlink satellites:\n")
        for sat in catalog[:20]:
            inc = float(sat.get("INCLINATION") or 0)
            alt = float(sat.get("PERIAPSIS") or 0)
            print(
                f"  {sat['NORAD_CAT_ID']:>7}  {sat['OBJECT_NAME']:<25} "
                f"inc={inc:5.1f}°  alt={alt:6.1f}km  "
                f"launched={sat.get('LAUNCH_DATE', '?')}"
            )
        if len(catalog) > 20:
            print(f"  ... and {len(catalog) - 20} more")
    finally:
        db.close()
        client.close()


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="starloom",
        description="Starlink constellation data acquisition",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command")

    # fetch
    p_fetch = sub.add_parser("fetch", help="Download GP history for all Starlink satellites")
    p_fetch.add_argument("--db", default=config.DEFAULT_DB_PATH, help="Database path")
    p_fetch.add_argument("--start-date", help="Start date (default: per satellite launch date)")
    p_fetch.add_argument("--end-date", help="End date (default: today)")
    p_fetch.add_argument("--dry-run", action="store_true", help="Show plan without fetching")
    p_fetch.add_argument("--bulk-dir", default=config.DEFAULT_BULK_DIR,
                         help="Directory of bulk TLE zip/txt files to import first")

    # status
    p_status = sub.add_parser("status", help="Show fetch progress")
    p_status.add_argument("--db", default=config.DEFAULT_DB_PATH)

    # catalog
    p_catalog = sub.add_parser("catalog", help="List all Starlink satellites")
    p_catalog.add_argument("--db", default=config.DEFAULT_DB_PATH)

    # import-launches
    p_import = sub.add_parser("import-launches", help="Import launch data from xlsx")
    p_import.add_argument("xlsx", help="Path to starlink_launches.xlsx")
    p_import.add_argument("--db", default=config.DEFAULT_DB_PATH)

    # import-bulk
    p_bulk = sub.add_parser("import-bulk", help="Import bulk TLE zip/text files")
    p_bulk.add_argument("path", help="Directory of zip/txt files, or a single file")
    p_bulk.add_argument("--db", default=config.DEFAULT_DB_PATH)

    # verify-bulk
    p_verify = sub.add_parser("verify-bulk", help="Verify bulk TLE data against API records")
    p_verify.add_argument("path", help="Bulk TLE file to verify")
    p_verify.add_argument("--db", default=config.DEFAULT_DB_PATH)
    p_verify.add_argument("--sample-size", type=int, default=200, help="Number of pairs to compare")

    # render
    p_render = sub.add_parser("render", help="Render a single frame")
    p_render.add_argument("timestamp", help="Timestamp to render (e.g. 2019-07-01)")
    p_render.add_argument("--db", default=config.DEFAULT_DB_PATH)
    p_render.add_argument("--output", "-o", default="frame.png", help="Output file path")
    p_render.add_argument("--width", type=int, default=1920)
    p_render.add_argument("--height", type=int, default=1080)
    p_render.add_argument("--inclination", type=float, help="Filter to specific inclination (e.g. 53)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "catalog":
        cmd_catalog(args)
    elif args.command == "import-launches":
        from .import_launches import import_launches
        db = Database(args.db)
        try:
            import_launches(db, args.xlsx)
        finally:
            db.close()
    elif args.command == "import-bulk":
        from .bulk.importer import import_bulk
        db = Database(args.db)
        try:
            import_bulk(db, args.path)
            latest = db.get_latest_epoch()
            if latest:
                print(f"\nLatest epoch in database: {latest[:10]}")
                print("Run 'starloom fetch' to pick up from where bulk data ends.")
        finally:
            db.close()
    elif args.command == "verify-bulk":
        from .bulk.verify import verify_bulk
        db = Database(args.db)
        try:
            verify_bulk(db, args.path, sample_size=args.sample_size)
        finally:
            db.close()
    elif args.command == "render":
        from datetime import datetime
        db = Database(args.db)
        try:
            ts = datetime.fromisoformat(args.timestamp)
            render_frame(db, ts, args.output, args.width, args.height,
                         inclination=args.inclination)
        finally:
            db.close()
