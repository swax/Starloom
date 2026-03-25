"""Batch fetching orchestrator for Starlink GP history data."""

import logging
import os
from datetime import date, timedelta

from .. import config
from ..database import Database
from .client import SpaceTrackClient

logger = logging.getLogger(__name__)


def _date_windows(
    start: date, end: date, days_per_window: int
) -> list[tuple[str, str]]:
    """Generate (start, end) date string pairs covering the range."""
    windows = []
    current = start
    while current < end:
        window_end = min(current + timedelta(days=days_per_window), end)
        windows.append((current.isoformat(), window_end.isoformat()))
        current = window_end
    return windows


def _ids_key(norad_ids: list[int]) -> str:
    """Create a stable string key for a batch of NORAD IDs."""
    return ",".join(str(i) for i in sorted(norad_ids))


class Fetcher:
    def __init__(
        self,
        client: SpaceTrackClient,
        db: Database,
        ids_per_batch: int = config.NORAD_IDS_PER_BATCH,
        days_per_batch: int = config.EPOCH_DAYS_PER_BATCH,
    ):
        self.client = client
        self.db = db
        self.ids_per_batch = ids_per_batch
        self.days_per_batch = days_per_batch

    def discover_satellites(self) -> None:
        """Fetch the full Starlink catalog and store it."""
        logger.info("Fetching Starlink satellite catalog...")
        catalog = self.client.fetch_starlink_catalog()
        count = self.db.upsert_satellites(catalog)
        logger.info(f"Catalog: {count} Starlink satellites stored")

    def _build_work_items(
        self, end_date: date, start_date: date | None = None
    ) -> list[tuple[list[int], str, str]]:
        """Build work items ordered by date window first, then satellite batch.

        This means we get a snapshot of ALL satellites for each time period
        before moving to the next, which is better for rendering early.
        """
        satellites = self.db.get_satellites()  # sorted by launch date

        # Build satellite batches with their earliest applicable date
        sat_batches: list[tuple[list[int], date]] = []
        end = end_date

        for i in range(0, len(satellites), self.ids_per_batch):
            batch = satellites[i : i + self.ids_per_batch]
            norad_ids = [row[0] for row in batch]
            launch_dates = [row[1] for row in batch if row[1]]

            if launch_dates:
                earliest = date.fromisoformat(min(launch_dates)) - timedelta(days=1)
            else:
                earliest = end - timedelta(days=90)

            sat_batches.append((norad_ids, earliest))

        # Find the global earliest start date (or use override)
        global_start = start_date or min(s[1] for s in sat_batches)
        all_windows = _date_windows(global_start, end_date, self.days_per_batch)

        # Iterate: date windows outer, satellite batches inner
        # Skip batches whose satellites didn't exist yet in that window
        work_items: list[tuple[list[int], str, str]] = []
        for win_start, win_end in all_windows:
            win_start_date = date.fromisoformat(win_start)
            for norad_ids, batch_earliest in sat_batches:
                if win_start_date >= batch_earliest:
                    work_items.append((norad_ids, win_start, win_end))

        return work_items

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

        First imports any bulk TLE files from bulk_dir, then uses
        the API for the remaining gap.
        """
        start = date.fromisoformat(start_date) if start_date else None
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

        # Auto-detect start from existing data if not specified
        if start is None:
            latest = self.db.get_latest_epoch()
            if latest:
                start = date.fromisoformat(latest[:10])
                logger.info(
                    f"Existing data through {start}, fetching from there"
                )

        # Phase 3: generate work items (launch-date-aware)
        work_items = self._build_work_items(end, start)
        total_items = len(work_items)

        # Count how many are already done
        already_done = sum(
            1 for ids, ws, we in work_items
            if self.db.is_batch_fetched(_ids_key(ids), ws, we)
        )
        remaining = total_items - already_done

        logger.info(
            f"{sat_count} satellites, {total_items} work items "
            f"({already_done} already done, {remaining} remaining)"
        )

        est_hours = remaining * config.MIN_REQUEST_INTERVAL_SECONDS / 3600
        if dry_run:
            logger.info(f"Dry run — estimated fetch time: {est_hours:.1f} hours")
            return

        if remaining == 0:
            logger.info("Nothing to fetch — all work items already done")
            return

        # Confirm before hitting the API
        print(
            f"\nAbout to make {remaining} gp_history API requests "
            f"(~{est_hours:.1f} hours)."
        )
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

        # Phase 4: execute
        completed = 0
        total_records = 0

        for item_num, (norad_ids, win_start, win_end) in enumerate(work_items, 1):
            ids_key = _ids_key(norad_ids)

            if self.db.is_batch_fetched(ids_key, win_start, win_end):
                continue

            try:
                records = self.client.fetch_gp_history_batch(
                    norad_ids, win_start, win_end
                )
            except Exception as e:
                logger.error(f"Batch {item_num}/{total_items} failed: {e}")
                continue

            new_count = self.db.insert_gp_records(records)
            self.db.mark_batch_fetched(ids_key, win_start, win_end, len(records))
            self.db.commit()

            completed += 1
            total_records += new_count

            logger.info(
                f"Progress: {completed}/{remaining} | "
                f"{total_records} new records | "
                f"IDs {norad_ids[0]}..{norad_ids[-1]}, "
                f"epoch {win_start}..{win_end} → {len(records)} records"
            )

        logger.info(
            f"Done: {completed} batches fetched, "
            f"{total_records} new records inserted"
        )
