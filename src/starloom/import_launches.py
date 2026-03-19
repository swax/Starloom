"""Import launch data from starlink_launches.xlsx into the database."""

import logging

import openpyxl

from .database import Database

logger = logging.getLogger(__name__)


def import_launches(db: Database, xlsx_path: str) -> None:
    """Read the All Launches sheet and import into the launches table."""
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb["All Launches"]

    launches = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            break
        mission_name = row[1]
        shell = row[2]
        launch_date = row[3]
        cospar_id = row[4]
        sats_launched = row[5]

        if not cospar_id or not launch_date:
            continue

        launches.append({
            "cospar_id": str(cospar_id).strip(),
            "mission_name": str(mission_name),
            "shell": str(shell),
            "launch_date": launch_date.strftime("%Y-%m-%d"),
            "sats_launched": int(sats_launched) if sats_launched else 0,
        })

    count = db.upsert_launches(launches)
    logger.info(f"Imported {count} launches")

    linked = db.link_satellites_to_launches()
    logger.info(f"Linked {linked} satellites to launches")

    # Report coverage
    total = db.get_satellite_count()
    linked_count = db._conn.execute(
        "SELECT COUNT(*) FROM satellites WHERE cospar_id IS NOT NULL"
    ).fetchone()[0]
    unlinked = total - linked_count
    logger.info(f"Satellite coverage: {linked_count}/{total} linked, {unlinked} unlinked")

    # Show shell distribution
    rows = db._conn.execute("""
        SELECT l.shell, COUNT(*) as count
        FROM satellites s
        JOIN launches l ON s.cospar_id = l.cospar_id
        GROUP BY l.shell
        ORDER BY count DESC
    """).fetchall()
    for shell, count in rows:
        logger.info(f"  {shell}: {count} satellites")
