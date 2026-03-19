"""Render a single frame of the Starlink constellation at a given timestamp."""

import logging
import math
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib

from .database import Database

logger = logging.getLogger(__name__)

# Earth/orbital constants
J2 = 1.08263e-3
R_EARTH_KM = 6378.137
MU = 398600.4418  # km³/s²

# Reference epoch for co-precessing frame
REFERENCE_EPOCH = datetime(2019, 5, 24)  # First Starlink launch

# Inclination bands: (min, max, color, label)
INCLINATION_BANDS = [
    (41, 45, "#FFD54F", "43°"),
    (51, 55, "#42A5F5", "53°"),
    (68, 72, "#FF7043", "70°"),
    (95, 100, "#AB47BC", "97°"),
]
DEFAULT_COLOR = "#FFFFFF"


def _color_for_inclination(inc: float) -> tuple[str, str]:
    """Return (color, label) for a given inclination."""
    for lo, hi, color, label in INCLINATION_BANDS:
        if lo <= inc <= hi:
            return color, label
    return DEFAULT_COLOR, f"{inc:.0f}°"


def _j2_raan_precession_rate(inclination_deg: float, semi_major_axis_km: float,
                              eccentricity: float) -> float:
    """Compute J2 RAAN precession rate in degrees/day."""
    i = math.radians(inclination_deg)
    a = semi_major_axis_km
    e = eccentricity
    n = math.sqrt(MU / a**3)  # mean motion in rad/s

    rate_rad_s = -1.5 * n * J2 * (R_EARTH_KM / a)**2 * math.cos(i) / (1 - e**2)**2
    return math.degrees(rate_rad_s) * 86400  # convert to deg/day


def _precession_rate_for_inclination(inc_deg: float) -> float:
    """Reference precession rate for a given inclination at typical Starlink altitude."""
    a = R_EARTH_KM + 550
    return _j2_raan_precession_rate(inc_deg, a, 0.0001)


def get_frame_data(db: Database, timestamp: datetime,
                   ref_inclination: float | None = None) -> list[dict]:
    """Get satellite positions for a given timestamp.

    Finds the nearest TLE for each satellite within ±1 day of the timestamp,
    computes argument of latitude and co-precessing RAAN.
    """
    ts_str = timestamp.isoformat()

    all_rows = db._conn.execute("""
        SELECT
            h.NORAD_CAT_ID,
            h.OBJECT_NAME,
            h.EPOCH,
            h.INCLINATION,
            h.RA_OF_ASC_NODE,
            h.ARG_OF_PERICENTER,
            h.MEAN_ANOMALY,
            h.ECCENTRICITY,
            h.SEMIMAJOR_AXIS,
            h.MEAN_MOTION,
            l.shell
        FROM gp_history h
        LEFT JOIN satellites s ON h.NORAD_CAT_ID = s.NORAD_CAT_ID
        LEFT JOIN launches l ON s.cospar_id = l.cospar_id
        WHERE ABS(julianday(h.EPOCH) - julianday(?)) < 1.0
        ORDER BY h.NORAD_CAT_ID, ABS(julianday(h.EPOCH) - julianday(?))
    """, (ts_str, ts_str)).fetchall()

    # Keep only the nearest TLE per satellite
    seen: set[int] = set()
    rows = []
    for row in all_rows:
        norad_id = row[0]
        if norad_id not in seen:
            seen.add(norad_id)
            rows.append(row)

    # Cache precession rates by rounded inclination
    precession_cache: dict[float, float] = {}

    points = []
    for row in rows:
        (norad_id, name, epoch_str, inc, raan, argp, ma,
         ecc, sma, mm, shell) = row

        if any(v is None for v in (inc, raan, argp, ma, mm, sma)):
            continue

        inc_f = float(inc)
        epoch = datetime.fromisoformat(epoch_str)
        dt_days = (timestamp - epoch).total_seconds() / 86400

        # Propagate mean anomaly to target timestamp
        mm_deg_per_day = float(mm) * 360.0
        propagated_ma = (float(ma) + mm_deg_per_day * dt_days) % 360.0

        # Argument of latitude (anomaly past ascending node)
        arg_lat = (float(argp) + propagated_ma) % 360.0

        # Co-precessing RAAN: use per-satellite inclination by default,
        # or the specified reference inclination if filtering
        rate_inc = ref_inclination if ref_inclination is not None else inc_f
        inc_key = round(rate_inc, 1)
        if inc_key not in precession_cache:
            precession_cache[inc_key] = _precession_rate_for_inclination(rate_inc)
        ref_rate = precession_cache[inc_key]

        days_since_ref = (epoch - REFERENCE_EPOCH).total_seconds() / 86400
        co_raan = (float(raan) - ref_rate * days_since_ref) % 360.0

        # Altitude from semi-major axis
        altitude = float(sma) - R_EARTH_KM

        # Operational if above 350km (below = deorbiting or raising)
        # Sats below ~300km are clearly deorbiting, 300-350 is marginal
        operational = altitude >= 350

        points.append({
            "norad_id": norad_id,
            "name": name,
            "arg_lat": arg_lat,
            "co_raan": co_raan,
            "inclination": float(inc),
            "shell": shell,
            "altitude": altitude,
            "operational": operational,
        })

    return points


def render_frame(db: Database, timestamp: datetime, output_path: str,
                 width: int = 1920, height: int = 1080,
                 inclination: float | None = None, inc_tolerance: float = 2.0) -> None:
    """Render a single frame to an image file."""
    points = get_frame_data(db, timestamp, ref_inclination=inclination)

    if inclination is not None:
        points = [p for p in points
                  if abs(p["inclination"] - inclination) <= inc_tolerance]
    logger.info(f"Rendering {len(points)} satellites at {timestamp.isoformat()}")

    if not points:
        logger.warning("No data for this timestamp")
        return

    # Scale sizes relative to 1080p baseline
    scale = height / 1080
    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.set_facecolor("black")
    ax.set_facecolor("black")

    # Group by shell for legend, but color dots by actual inclination
    shells: dict[str, list[dict]] = {}
    for p in points:
        shells.setdefault(p["shell"] or "Unknown", []).append(p)

    op_count = sum(1 for p in points if p["operational"])
    non_op_count = len(points) - op_count

    # Draw dots colored by actual inclination
    for operational, alpha, size in [(False, 0.2, 2 * scale), (True, 0.9, 3 * scale)]:
        filtered = [p for p in points if p["operational"] == operational]
        if not filtered:
            continue
        x = [p["co_raan"] for p in filtered]
        y = [p["arg_lat"] for p in filtered]
        colors = [_color_for_inclination(p["inclination"])[0] for p in filtered]
        ax.scatter(x, y, s=size, c=colors, edgecolors="none", linewidths=0, alpha=alpha)

    # Add invisible legend entries per shell (colored by shell's inclination band)
    for shell_name, pts in sorted(shells.items()):
        avg_inc = sum(p["inclination"] for p in pts) / len(pts)
        color, _ = _color_for_inclination(avg_inc)
        ax.scatter([], [], s=10 * scale, c=color, label=f"{shell_name} ({len(pts)})")

    ax.set_xlim(0, 360)
    ax.set_ylim(360, 0)  # 0 at top, 360 at bottom
    ax.set_xlabel("Co-precessing Longitude of Ascending Node (°)",
                  color="white", fontsize=10 * scale, labelpad=10 * scale)
    ax.set_ylabel("Anomaly Past Ascending Node (°)",
                  color="white", fontsize=10 * scale, labelpad=10 * scale)

    # Title
    if inclination is not None:
        title_text = f"Starlink Constellation at {inclination:.0f}° — {op_count:,} operational, {non_op_count:,} transitioning"
    else:
        title_text = f"Starlink Constellation — {op_count:,} operational, {non_op_count:,} transitioning"
    fig.text(0.06, 0.97, title_text,
             color="white", fontsize=14 * scale, fontweight="bold", va="top")
    fig.text(0.98, 0.97, "Rendered with Starloom",
             color="gray", fontsize=10 * scale, va="top", ha="right")
    fig.text(0.60, 0.97, timestamp.strftime("%Y-%m-%d %H:%M UTC"),
             color="white", fontsize=14 * scale, va="top", ha="center")

    ax.tick_params(colors="white", labelsize=9 * scale)
    for spine in ax.spines.values():
        spine.set_color("white")

    ax.set_xticks(range(0, 361, 30))
    ax.set_yticks(range(0, 361, 30))
    ax.grid(True, alpha=0.15, color="white")

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08),
              ncol=min(len(shells), 5), fontsize=11 * scale, framealpha=0.3,
              facecolor="black", edgecolor="gray", labelcolor="white",
              markerscale=1.2 * scale)

    plt.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.17)
    plt.savefig(output_path, facecolor="black", dpi=dpi)
    plt.close()
    logger.info(f"Saved: {output_path}")
