"""SQLite database for storing GP history and fetch progress."""

import logging
import sqlite3

from . import config

logger = logging.getLogger(__name__)

# Columns we store from GP_HISTORY JSON responses
GP_COLUMNS = [
    "GP_ID", "NORAD_CAT_ID", "OBJECT_NAME", "OBJECT_ID", "EPOCH",
    "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT", "REV_AT_EPOCH", "CLASSIFICATION_TYPE",
    "ELEMENT_SET_NO", "EPHEMERIS_TYPE", "SEMIMAJOR_AXIS", "PERIOD",
    "APOAPSIS", "PERIAPSIS", "OBJECT_TYPE", "RCS_SIZE", "COUNTRY_CODE",
    "LAUNCH_DATE", "SITE", "DECAY_DATE", "FILE", "TLE_LINE0",
    "TLE_LINE1", "TLE_LINE2", "CREATION_DATE",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS satellites (
    NORAD_CAT_ID    INTEGER PRIMARY KEY,
    OBJECT_NAME     TEXT,
    LAUNCH_DATE     TEXT,
    DECAY_DATE      TEXT,
    INCLINATION     REAL,
    PERIOD          REAL,
    APOAPSIS        REAL,
    PERIAPSIS       REAL
);

CREATE TABLE IF NOT EXISTS gp_history (
    GP_ID               INTEGER PRIMARY KEY,
    NORAD_CAT_ID        INTEGER NOT NULL,
    OBJECT_NAME         TEXT,
    OBJECT_ID           TEXT,
    EPOCH               TEXT NOT NULL,
    MEAN_MOTION         REAL,
    ECCENTRICITY        REAL,
    INCLINATION         REAL,
    RA_OF_ASC_NODE      REAL,
    ARG_OF_PERICENTER   REAL,
    MEAN_ANOMALY        REAL,
    BSTAR               REAL,
    MEAN_MOTION_DOT     REAL,
    MEAN_MOTION_DDOT    REAL,
    REV_AT_EPOCH        INTEGER,
    CLASSIFICATION_TYPE TEXT,
    ELEMENT_SET_NO      INTEGER,
    EPHEMERIS_TYPE      INTEGER,
    SEMIMAJOR_AXIS      REAL,
    PERIOD              REAL,
    APOAPSIS            REAL,
    PERIAPSIS           REAL,
    OBJECT_TYPE         TEXT,
    RCS_SIZE            TEXT,
    COUNTRY_CODE        TEXT,
    LAUNCH_DATE         TEXT,
    SITE                TEXT,
    DECAY_DATE          TEXT,
    FILE                INTEGER,
    TLE_LINE0           TEXT,
    TLE_LINE1           TEXT,
    TLE_LINE2           TEXT,
    CREATION_DATE       TEXT
);

CREATE INDEX IF NOT EXISTS idx_gp_norad_epoch
    ON gp_history(NORAD_CAT_ID, EPOCH);

CREATE INDEX IF NOT EXISTS idx_gp_epoch
    ON gp_history(EPOCH);

CREATE TABLE IF NOT EXISTS fetch_progress (
    norad_cat_ids   TEXT NOT NULL,
    epoch_start     TEXT NOT NULL,
    epoch_end       TEXT NOT NULL,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    record_count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (norad_cat_ids, epoch_start, epoch_end)
);
"""


class Database:
    def __init__(self, db_path: str = config.DEFAULT_DB_PATH):
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        logger.info(f"Database opened: {db_path}")

    def upsert_satellites(self, catalog: list[dict]) -> int:
        """Store satellite catalog entries. Returns count inserted/updated."""
        sql = (
            "INSERT OR REPLACE INTO satellites "
            "(NORAD_CAT_ID, OBJECT_NAME, LAUNCH_DATE, DECAY_DATE, "
            "INCLINATION, PERIOD, APOAPSIS, PERIAPSIS) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        rows = [
            (
                int(sat["NORAD_CAT_ID"]),
                sat.get("OBJECT_NAME"),
                sat.get("LAUNCH_DATE"),
                sat.get("DECAY_DATE"),
                sat.get("INCLINATION"),
                sat.get("PERIOD"),
                sat.get("APOAPSIS"),
                sat.get("PERIAPSIS"),
            )
            for sat in catalog
        ]
        self._conn.executemany(sql, rows)
        self._conn.commit()
        return len(rows)

    def get_satellites(self) -> list[tuple[int, str | None]]:
        """Return all satellites as (NORAD_CAT_ID, LAUNCH_DATE) sorted by launch date.

        Satellites with no launch date sort last (they're typically recent
        unassigned sats that shouldn't be queried back to 2019).
        """
        rows = self._conn.execute(
            "SELECT NORAD_CAT_ID, LAUNCH_DATE FROM satellites "
            "ORDER BY CASE WHEN LAUNCH_DATE IS NULL OR LAUNCH_DATE = '' "
            "THEN 1 ELSE 0 END, LAUNCH_DATE, NORAD_CAT_ID"
        ).fetchall()
        return rows

    def get_satellite_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM satellites").fetchone()
        return row[0]

    def insert_gp_records(self, records: list[dict]) -> int:
        """Insert GP records, ignoring duplicates. Returns count of new records."""
        if not records:
            return 0

        placeholders = ", ".join(["?"] * len(GP_COLUMNS))
        cols = ", ".join(GP_COLUMNS)
        sql = f"INSERT OR IGNORE INTO gp_history ({cols}) VALUES ({placeholders})"

        rows = []
        for rec in records:
            row = tuple(rec.get(col) for col in GP_COLUMNS)
            rows.append(row)

        cursor = self._conn.executemany(sql, rows)
        return cursor.rowcount

    def mark_batch_fetched(
        self,
        norad_cat_ids: str,
        epoch_start: str,
        epoch_end: str,
        record_count: int,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO fetch_progress "
            "(norad_cat_ids, epoch_start, epoch_end, record_count) "
            "VALUES (?, ?, ?, ?)",
            (norad_cat_ids, epoch_start, epoch_end, record_count),
        )

    def is_batch_fetched(
        self, norad_cat_ids: str, epoch_start: str, epoch_end: str
    ) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM fetch_progress "
            "WHERE norad_cat_ids = ? AND epoch_start = ? AND epoch_end = ?",
            (norad_cat_ids, epoch_start, epoch_end),
        ).fetchone()
        return row is not None

    def commit(self) -> None:
        self._conn.commit()

    def get_record_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM gp_history").fetchone()
        return row[0]

    def get_fetch_progress_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM fetch_progress").fetchone()
        return row[0]

    def close(self) -> None:
        self._conn.close()
        logger.info("Database closed")
