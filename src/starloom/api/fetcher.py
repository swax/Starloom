"""Batch fetching orchestrator for Starlink GP history data."""

import logging
import os
from datetime import date, timedelta

from .. import config
from ..database import Database
from .client import SpaceTrackClient

logger = logging.getLogger(__name__)


class Fetcher:
    def __init__(self, client: SpaceTrackClient, db: Database):
        self.client = client
        self.db = db

    def discover_satellites(self) -> None:
        """Fetch the full Starlink catalog and store it."""
        logger.info("Fetching Starlink satellite catalog...")
        catalog = self.client.fetch_starlink_catalog()
        count = self.db.upsert_satellites(catalog)
        logger.info(f"Catalog: {count} Starlink satellites stored")

    def _import_bulk_if_available(self, bulk_dir: str) -> None:
        """Import any zip/txt files found in bulk_dir."""
        if not os.path.isdir(bulk_dir):
            return

        from ..bulk.importer import _collect_files, import_bulk

        files = _collect_files(bulk_dir)
        if not files:
            return

        logger.info(f"Found {len(files)} bulk file(s) in {bulk_dir}")
        import_bulk(self.db, bulk_dir)

    def run(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        dry_run: bool = False,
        bulk_dir: str = config.DEFAULT_BULK_DIR,
    ) -> None:
        """Run the full fetch pipeline.

        Imports bulk TLE files first, then uses the Space-Track API to
        fetch remaining days one at a time by CREATION_DATE.
        """
        end = date.fromisoformat(end_date or date.today().isoformat())

        # Phase 1: refresh catalog from API (non-fatal — may already be populated)
        try:
            self.discover_satellites()
        except Exception as e:
            sat_count = self.db.get_satellite_count()
            if sat_count > 0:
                logger.warning(
                    f"Could not refresh catalog ({e}), "
                    f"using {sat_count} existing satellites"
                )
            else:
                logger.error(f"No satellites in database and catalog fetch failed: {e}")
                return

        # Phase 2: import bulk TLE files if available
        self._import_bulk_if_available(bulk_dir)

        sat_count = self.db.get_satellite_count()
        if sat_count == 0:
            logger.error("No satellites found — run 'starloom catalog' first")
            return

        # Determine start date for API queries
        if start_date:
            start = date.fromisoformat(start_date)
        else:
            latest = self.db.get_latest_fetched_date()
            if latest:
                # Resume from the day after the last fetched date
                start = date.fromisoformat(latest) + timedelta(days=1)
                logger.info(f"Last fetched: {latest}, resuming from {start}")
            else:
                start = date.fromisoformat(config.API_START_DATE)
                logger.info(
                    f"No API fetch history, starting from {config.API_START_DATE}"
                )

        # Build list of dates to fetch (up to but not including end,
        # since today's data may be incomplete until after 0000 UTC)
        dates_to_fetch: list[date] = []
        current = start
        while current < end:
            if not self.db.is_date_fetched(current.isoformat()):
                dates_to_fetch.append(current)
            current += timedelta(days=1)

        remaining = len(dates_to_fetch)
        logger.info(f"{sat_count} satellites, {remaining} days to fetch")

        est_minutes = remaining * config.MIN_REQUEST_INTERVAL_SECONDS / 60

        if dry_run:
            logger.info(f"Dry run — estimated fetch time: {est_minutes:.1f} minutes")
            return

        if remaining == 0:
            logger.info("Up to date — nothing to fetch")
            return

        # Confirm before hitting the API
        print(
            f"\nAbout to make {remaining} API requests "
            f"(~{est_minutes:.1f} minutes)."
        )
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

        # Phase 3: fetch each day by CREATION_DATE
        starlink_ids = self.db.get_starlink_norad_ids()
        total_records = 0

        for i, fetch_date in enumerate(dates_to_fetch, 1):
            date_str = fetch_date.isoformat()

            try:
                records = self.client.fetch_gp_history_by_date(date_str)
            except Exception as e:
                logger.error(f"Day {date_str} failed: {e}")
                continue

            # Filter to known Starlink satellites
            starlink_records = [
                r for r in records
                if int(r.get("NORAD_CAT_ID", 0)) in starlink_ids
            ]

            new_count = self.db.insert_gp_records(starlink_records)
            self.db.mark_date_fetched(date_str, len(starlink_records))
            self.db.commit()

            total_records += new_count

            logger.info(
                f"[{i}/{remaining}] {date_str}: "
                f"{len(starlink_records)} Starlink records "
                f"(of {len(records)} total), {new_count} new"
            )

        logger.info(f"Done: {total_records} new records inserted")
