"""Batch fetching orchestrator for Starlink GP history data."""

import logging
from datetime import date, timedelta

from . import config
from .database import Database
from .spacetrack_client import SpaceTrackClient

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
        self, end_date: date
    ) -> list[tuple[list[int], str, str]]:
        """Build work items grouped by launch date to skip impossible windows."""
        satellites = self.db.get_satellites()  # sorted by launch date

        # Group into batches of ids_per_batch
        work_items: list[tuple[list[int], str, str]] = []

        for i in range(0, len(satellites), self.ids_per_batch):
            batch = satellites[i : i + self.ids_per_batch]
            norad_ids = [row[0] for row in batch]
            launch_dates = [row[1] for row in batch if row[1]]

            # Start from earliest launch date in this batch (minus a day for early TLEs)
            if launch_dates:
                earliest = date.fromisoformat(min(launch_dates)) - timedelta(days=1)
            else:
                # No launch date = likely recent unassigned sats; query last 90 days
                earliest = end - timedelta(days=90)

            windows = _date_windows(earliest, end_date, self.days_per_batch)
            for win_start, win_end in windows:
                work_items.append((norad_ids, win_start, win_end))

        return work_items

    def run(
        self,
        end_date: str | None = None,
        dry_run: bool = False,
    ) -> None:
        """Run the full fetch pipeline."""
        end = date.fromisoformat(end_date or date.today().isoformat())

        # Phase 1: discover all Starlink satellites
        self.discover_satellites()

        sat_count = self.db.get_satellite_count()
        if sat_count == 0:
            logger.error("No satellites found")
            return

        # Phase 2: generate work items (launch-date-aware)
        work_items = self._build_work_items(end)
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

        if dry_run:
            est_hours = remaining * config.MIN_REQUEST_INTERVAL_SECONDS / 3600
            logger.info(f"Dry run — estimated fetch time: {est_hours:.1f} hours")
            return

        # Phase 3: execute
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
