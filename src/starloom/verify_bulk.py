"""Verify bulk TLE files against existing API records without importing."""

import logging
import os

from .database import Database
from .tle_parser import parse_tle_lines

logger = logging.getLogger(__name__)

COMPARE_FIELDS = [
    ("MEAN_MOTION", 1e-8),
    ("ECCENTRICITY", 1e-8),
    ("INCLINATION", 1e-4),
    ("RA_OF_ASC_NODE", 1e-4),
    ("ARG_OF_PERICENTER", 1e-4),
    ("MEAN_ANOMALY", 1e-4),
    ("BSTAR", 1e-10),
    ("MEAN_MOTION_DOT", 1e-8),
    ("MEAN_MOTION_DDOT", 1e-10),
    ("REV_AT_EPOCH", 0),
    ("SEMIMAJOR_AXIS", 0.1),
    ("PERIOD", 0.01),
    ("APOAPSIS", 0.1),
    ("PERIAPSIS", 0.1),
]


def verify_bulk(db: Database, path: str, sample_size: int = 200) -> None:
    """Parse a bulk TLE file and compare records against API data in the DB.

    Matches on (NORAD_CAT_ID, EPOCH). Does NOT insert anything.
    """
    norad_ids = db.get_starlink_norad_ids()
    if not norad_ids:
        print("No satellites in database. Run 'starloom catalog' first.")
        return

    # Build a lookup of API records by (NORAD_CAT_ID, EPOCH)
    print("Loading API records for comparison...")
    api_lookup: dict[tuple[int, str], dict] = {}
    rows = db._conn.execute(
        "SELECT NORAD_CAT_ID, EPOCH, MEAN_MOTION, ECCENTRICITY, INCLINATION, "
        "RA_OF_ASC_NODE, ARG_OF_PERICENTER, MEAN_ANOMALY, BSTAR, "
        "MEAN_MOTION_DOT, MEAN_MOTION_DDOT, REV_AT_EPOCH, "
        "SEMIMAJOR_AXIS, PERIOD, APOAPSIS, PERIAPSIS "
        "FROM gp_history WHERE GP_ID > 0"
    )
    for row in rows:
        key = (row[0], row[1])
        api_lookup[key] = {
            "MEAN_MOTION": row[2], "ECCENTRICITY": row[3],
            "INCLINATION": row[4], "RA_OF_ASC_NODE": row[5],
            "ARG_OF_PERICENTER": row[6], "MEAN_ANOMALY": row[7],
            "BSTAR": row[8], "MEAN_MOTION_DOT": row[9],
            "MEAN_MOTION_DDOT": row[10], "REV_AT_EPOCH": row[11],
            "SEMIMAJOR_AXIS": row[12], "PERIOD": row[13],
            "APOAPSIS": row[14], "PERIAPSIS": row[15],
        }

    print(f"Loaded {len(api_lookup):,} API records")
    if not api_lookup:
        print("No API records found — nothing to compare.")
        return

    # Stream through bulk file, match against API records
    print(f"Scanning bulk file {os.path.basename(path)}...")
    matched = 0
    mismatches = 0
    parsed = 0
    field_mismatch_counts: dict[str, int] = {}

    with open(path, encoding="ascii", errors="replace") as f:
        for record in parse_tle_lines(iter(f), norad_filter=norad_ids):
            parsed += 1

            key = (record["NORAD_CAT_ID"], record["EPOCH"])
            api = api_lookup.get(key)
            if api is None:
                continue

            matched += 1

            for name, tolerance in COMPARE_FIELDS:
                api_val = api.get(name)
                bulk_val = record.get(name)
                if api_val is None or bulk_val is None:
                    continue
                diff = abs(float(api_val) - float(bulk_val))
                if diff > tolerance:
                    mismatches += 1
                    field_mismatch_counts[name] = field_mismatch_counts.get(name, 0) + 1
                    if mismatches <= 5:
                        print(
                            f"  MISMATCH: NORAD {record['NORAD_CAT_ID']}, "
                            f"epoch {record['EPOCH']}, "
                            f"{name}: API={api_val} vs bulk={bulk_val} "
                            f"(diff={diff:.2e})"
                        )

            if matched >= sample_size:
                break

            if parsed % 100000 == 0:
                logger.info(
                    f"  Scanned {parsed:,} Starlink TLEs, "
                    f"{matched} matches so far..."
                )

    # Summary
    print(f"\n{'='*60}")
    print(f"Starlink TLEs scanned: {parsed:,}")
    print(f"Matched to API data:   {matched}")
    print(f"Fields checked:        {len(COMPARE_FIELDS)} per pair")

    if matched == 0:
        print("\nNo matching TLEs found. The bulk file may not overlap "
              "with existing API data.")
    elif mismatches == 0:
        print(f"Result:                ALL MATCH")
        print(f"\nBulk TLE parsing matches API data perfectly.")
    else:
        print(f"Mismatches:            {mismatches}")
        print(f"\nMismatches by field:")
        for name, count in sorted(
            field_mismatch_counts.items(), key=lambda x: -x[1]
        ):
            print(f"  {name:<25} {count}")
