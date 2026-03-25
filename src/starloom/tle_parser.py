"""Parse TLE (Two/Three-Line Element) text into gp_history-compatible dicts."""

import hashlib
import math
from datetime import datetime, timedelta
from typing import IO, Iterator

# Earth constants (same as render.py)
MU = 398600.4418  # km³/s²
R_EARTH_KM = 6378.137


def _parse_tle_decimal(s: str) -> float:
    """Parse TLE assumed-decimal-point notation like ' 12345-4' → 0.12345e-4."""
    s = s.strip()
    if not s or s == "0" * len(s):
        return 0.0

    sign = -1.0 if s[0] == "-" else 1.0
    if s[0] in "+-":
        s = s[1:]

    # Find exponent delimiter (last +/- in the string)
    for i in range(len(s) - 1, 0, -1):
        if s[i] in "+-":
            mantissa = "0." + s[:i]
            exponent = s[i:]
            return sign * float(mantissa + "e" + exponent)

    return sign * float("0." + s)


def _epoch_to_iso(epoch_year_2d: int, epoch_day: float) -> str:
    """Convert TLE epoch (2-digit year + fractional day) to ISO datetime string."""
    year = epoch_year_2d + (2000 if epoch_year_2d < 57 else 1900)
    dt = datetime(year, 1, 1) + timedelta(days=epoch_day - 1)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _intl_designator_to_object_id(piece: str) -> str:
    """Convert TLE international designator '19029D  ' to '2019-029D'."""
    piece = piece.strip()
    if len(piece) < 4:
        return piece
    yr = int(piece[:2])
    year = yr + (2000 if yr < 57 else 1900)
    rest = piece[2:]
    # Split into launch number (digits) and piece letter(s)
    i = 0
    while i < len(rest) and rest[i].isdigit():
        i += 1
    launch_num = rest[:i]
    piece_letter = rest[i:]
    return f"{year}-{launch_num.zfill(3)}{piece_letter}"


def _synthetic_gp_id(norad_cat_id: int, epoch: str) -> int:
    """Generate a deterministic negative GP_ID for bulk-imported records."""
    h = hashlib.md5(f"{norad_cat_id}:{epoch}".encode()).hexdigest()
    return -(int(h[:15], 16) % (2**62))


def _derived_orbital_params(
    mean_motion_rev_day: float, eccentricity: float
) -> tuple[float, float, float, float]:
    """Compute SEMIMAJOR_AXIS, PERIOD, APOAPSIS, PERIAPSIS from TLE elements."""
    if mean_motion_rev_day <= 0:
        return (0.0, 0.0, 0.0, 0.0)

    n_rad_s = mean_motion_rev_day * 2.0 * math.pi / 86400.0
    a = (MU / (n_rad_s**2)) ** (1.0 / 3.0)  # km
    period = 1440.0 / mean_motion_rev_day  # minutes
    apoapsis = a * (1.0 + eccentricity) - R_EARTH_KM  # km altitude
    periapsis = a * (1.0 - eccentricity) - R_EARTH_KM  # km altitude
    return (round(a, 3), round(period, 3), round(apoapsis, 3), round(periapsis, 3))


def parse_tle_lines(
    lines: Iterator[str],
    norad_filter: set[int] | None = None,
) -> Iterator[dict]:
    """Parse TLE text into gp_history-compatible dicts.

    Handles both 2LE (lines 1+2) and 3LE (line 0 + lines 1+2) formats.
    If norad_filter is provided, only yields records for those NORAD IDs.
    """
    line0: str | None = None
    line1: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            continue

        if line[0] == "0" and len(line) > 2 and line[1] == " ":
            line0 = line
            continue

        if line[0] == "1" and len(line) >= 69:
            line1 = line
            continue

        if line[0] == "2" and len(line) >= 69 and line1 is not None:
            # We have a complete TLE set
            record = _parse_tle_pair(line0, line1, line)
            line0 = None
            line1 = None

            if record is None:
                continue
            if norad_filter and record["NORAD_CAT_ID"] not in norad_filter:
                continue
            yield record
            continue

        # Non-TLE line or name without "0 " prefix (some files use bare names)
        if line[0] not in "012" and not line[0].isdigit():
            line0 = "0 " + line
            continue


def _parse_tle_pair(
    line0: str | None, line1: str, line2: str
) -> dict | None:
    """Parse a single TLE set (optional line 0 + lines 1 and 2) into a dict."""
    try:
        norad_cat_id = int(line1[2:7])

        classification = line1[7:8].strip()
        intl_desig = line1[9:17].strip()

        epoch_year = int(line1[18:20])
        epoch_day = float(line1[20:32])
        epoch = _epoch_to_iso(epoch_year, epoch_day)

        mean_motion_dot = float(line1[33:43])
        mean_motion_ddot = _parse_tle_decimal(line1[44:52])
        bstar = _parse_tle_decimal(line1[53:61])
        ephemeris_type = int(line1[62:63]) if line1[62:63].strip() else 0
        element_set_no = int(line1[64:68]) if line1[64:68].strip() else 0

        inclination = float(line2[8:16])
        ra_of_asc_node = float(line2[17:25])
        eccentricity = float("0." + line2[26:33].strip())
        arg_of_pericenter = float(line2[34:42])
        mean_anomaly = float(line2[43:51])
        mean_motion = float(line2[52:63])
        rev_at_epoch = int(line2[63:68]) if line2[63:68].strip() else 0

        sma, period, apoapsis, periapsis = _derived_orbital_params(
            mean_motion, eccentricity
        )

        object_name = None
        if line0:
            # Line 0 format: "0 STARLINK-1234" or just "STARLINK-1234"
            name = line0[2:].strip() if line0.startswith("0 ") else line0.strip()
            object_name = name

        object_id = _intl_designator_to_object_id(intl_desig) if intl_desig else None
        tle_line0 = f"0 {object_name}" if object_name else None

        return {
            "GP_ID": _synthetic_gp_id(norad_cat_id, epoch),
            "NORAD_CAT_ID": norad_cat_id,
            "OBJECT_NAME": object_name,
            "OBJECT_ID": object_id,
            "EPOCH": epoch,
            "MEAN_MOTION": mean_motion,
            "ECCENTRICITY": eccentricity,
            "INCLINATION": inclination,
            "RA_OF_ASC_NODE": ra_of_asc_node,
            "ARG_OF_PERICENTER": arg_of_pericenter,
            "MEAN_ANOMALY": mean_anomaly,
            "BSTAR": bstar,
            "MEAN_MOTION_DOT": mean_motion_dot,
            "MEAN_MOTION_DDOT": mean_motion_ddot,
            "REV_AT_EPOCH": rev_at_epoch,
            "CLASSIFICATION_TYPE": classification,
            "ELEMENT_SET_NO": element_set_no,
            "EPHEMERIS_TYPE": ephemeris_type,
            "SEMIMAJOR_AXIS": sma,
            "PERIOD": period,
            "APOAPSIS": apoapsis,
            "PERIAPSIS": periapsis,
            "OBJECT_TYPE": None,
            "RCS_SIZE": None,
            "COUNTRY_CODE": None,
            "LAUNCH_DATE": None,
            "SITE": None,
            "DECAY_DATE": None,
            "FILE": None,
            "TLE_LINE0": tle_line0,
            "TLE_LINE1": line1,
            "TLE_LINE2": line2,
            "CREATION_DATE": None,
        }
    except (ValueError, IndexError) as e:
        return None
