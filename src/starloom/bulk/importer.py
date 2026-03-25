"""Import bulk TLE zip/text files into the gp_history database."""

import io
import logging
import os
import zipfile

from ..database import Database
from .tle_parser import parse_tle_lines

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 5000


def import_bulk(db: Database, path: str) -> None:
    """Import TLE data from a directory of zip/txt files or a single file.

    Filters to only Starlink satellites already in the satellites table.
    """
    # Get the set of known Starlink NORAD IDs for filtering
    norad_ids = db.get_starlink_norad_ids()
    if not norad_ids:
        logger.error(
            "No satellites in database. Run 'starloom catalog' first to "
            "populate the Starlink satellite list."
        )
        return

    logger.info(f"Filtering to {len(norad_ids)} known Starlink satellites")

    files = _collect_files(path)
    if not files:
        logger.error(f"No .zip or .txt files found in {path}")
        return

    logger.info(f"Found {len(files)} file(s) to process")

    total_inserted = 0
    total_skipped = 0

    for filepath in sorted(files):
        inserted, skipped = _import_file(db, filepath, norad_ids)
        total_inserted += inserted
        total_skipped += skipped

    logger.info(
        f"Bulk import complete: {total_inserted:,} records inserted, "
        f"{total_skipped:,} duplicates skipped"
    )


def _collect_files(path: str) -> list[str]:
    """Collect .zip and .txt files from a path (file or directory)."""
    if os.path.isfile(path):
        return [path]

    files = []
    for name in os.listdir(path):
        if name.endswith((".zip", ".txt", ".tle")):
            files.append(os.path.join(path, name))
    return files


def _import_file(
    db: Database, filepath: str, norad_ids: set[int]
) -> tuple[int, int]:
    """Import a single zip or text file. Returns (inserted, skipped)."""
    basename = os.path.basename(filepath)
    logger.info(f"Processing {basename}...")

    total_inserted = 0
    total_skipped = 0

    if filepath.endswith(".zip"):
        with zipfile.ZipFile(filepath) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                logger.info(f"  Reading {info.filename} from zip...")
                with zf.open(info) as f:
                    text_stream = io.TextIOWrapper(f, encoding="ascii", errors="replace")
                    inserted, skipped = _import_lines(db, text_stream, norad_ids)
                    total_inserted += inserted
                    total_skipped += skipped
    else:
        with open(filepath, encoding="ascii", errors="replace") as f:
            total_inserted, total_skipped = _import_lines(db, f, norad_ids)

    logger.info(
        f"  {basename}: {total_inserted:,} inserted, {total_skipped:,} skipped"
    )
    return total_inserted, total_skipped


def _import_lines(
    db: Database, lines, norad_ids: set[int]
) -> tuple[int, int]:
    """Parse TLE lines and batch-insert into database. Returns (inserted, skipped)."""
    batch: list[dict] = []
    total_inserted = 0
    total_parsed = 0

    for record in parse_tle_lines(iter(lines), norad_filter=norad_ids):
        batch.append(record)
        total_parsed += 1

        if len(batch) >= INSERT_BATCH_SIZE:
            new = db.insert_gp_records(batch)
            total_inserted += new
            db.commit()
            batch.clear()

            if total_parsed % 50000 == 0:
                logger.info(f"    Parsed {total_parsed:,} Starlink TLEs...")

    if batch:
        new = db.insert_gp_records(batch)
        total_inserted += new
        db.commit()

    skipped = total_parsed - total_inserted
    return total_inserted, skipped
