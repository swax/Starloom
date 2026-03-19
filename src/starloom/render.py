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

# Shell colors — visually distinct on black background
SHELL_COLORS = {
    "Prototype":              "#888888",  # gray
    "Gen1 Shell 1 (53°)":    "#4FC3F7",  # light blue
    "Gen1 Shell 2 (70°)":    "#FF8A65",  # orange
    "Gen1 Shell 3 (polar 97.6°)": "#CE93D8",  # purple
    "Gen1 Shell 4 (53.2°)":  "#81C784",  # green
    "Gen1 Shell 5 (43°)":    "#FFF176",  # yellow
    "Gen2 Shell 1 (53°)":    "#29B6F6",  # blue
    "Gen2 Shell 2 (43°)":    "#FFD54F",  # amber
    "Gen2 Shell 3 (70°)":    "#FF7043",  # deep orange
    "Gen2 Shell 4 (97°)":    "#AB47BC",  # deep purple
    "Gen2 DTC Shell 1 (53°)": "#26C6DA",  # cyan
    "Gen2 DTC Shell 2 (43°)": "#FFCA28",  # gold
    "Shell 3 (70°, NRO)":    "#EF5350",  # red
    "Shell 3 (polar)":       "#EC407A",  # pink
}
DEFAULT_COLOR = "#FFFFFF"


def _j2_raan_precession_rate(inclination_deg: float, semi_major_axis_km: float,
                              eccentricity: float) -> float:
    """Compute J2 RAAN precession rate in degrees/day."""
    i = math.radians(inclination_deg)
    a = semi_major_axis_km
    e = eccentricity
    n = math.sqrt(MU / a**3)  # mean motion in rad/s

    rate_rad_s = -1.5 * n * J2 * (R_EARTH_KM / a)**2 * math.cos(i) / (1 - e**2)**2
    return math.degrees(rate_rad_s) * 86400  # convert to deg/day


def _nominal_precession_rate() -> float:
    """Reference precession rate for the 53° shell at 550km."""
    a = R_EARTH_KM + 550
    return _j2_raan_precession_rate(53.0, a, 0.0001)


def get_frame_data(db: Database, timestamp: datetime) -> list[dict]:
    """Get satellite positions for a given timestamp.

    Finds the nearest TLE for each satellite within ±1 day of the timestamp,
    computes argument of latitude and co-precessing RAAN.
    """
    ts_str = timestamp.isoformat()

    rows = db._conn.execute("""
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
        INNER JOIN (
            SELECT NORAD_CAT_ID, MIN(ABS(julianday(EPOCH) - julianday(?))) as min_diff
            FROM gp_history
            WHERE ABS(julianday(EPOCH) - julianday(?)) < 1.0
            GROUP BY NORAD_CAT_ID
        ) nearest ON h.NORAD_CAT_ID = nearest.NORAD_CAT_ID
            AND ABS(julianday(h.EPOCH) - julianday(?)) = nearest.min_diff
        LEFT JOIN satellites s ON h.NORAD_CAT_ID = s.NORAD_CAT_ID
        LEFT JOIN launches l ON s.cospar_id = l.cospar_id
    """, (ts_str, ts_str, ts_str)).fetchall()

    ref_rate = _nominal_precession_rate()  # deg/day

    points = []
    for row in rows:
        (norad_id, name, epoch_str, inc, raan, argp, ma,
         ecc, sma, mm, shell) = row

        if any(v is None for v in (inc, raan, argp, ma, mm)):
            continue

        epoch = datetime.fromisoformat(epoch_str)
        dt_days = (timestamp - epoch).total_seconds() / 86400

        # Propagate mean anomaly to target timestamp
        # Mean motion is in revolutions/day, convert to degrees/day
        mm_deg_per_day = float(mm) * 360.0
        propagated_ma = (float(ma) + mm_deg_per_day * dt_days) % 360.0

        # Argument of latitude (anomaly past ascending node)
        arg_lat = (float(argp) + propagated_ma) % 360.0

        # Co-precessing RAAN: remove reference precession drift
        days_since_ref = (epoch - REFERENCE_EPOCH).total_seconds() / 86400
        co_raan = (float(raan) - ref_rate * days_since_ref) % 360.0

        points.append({
            "norad_id": norad_id,
            "name": name,
            "arg_lat": arg_lat,
            "co_raan": co_raan,
            "inclination": float(inc),
            "shell": shell,
        })

    return points


def render_frame(db: Database, timestamp: datetime, output_path: str,
                 width: int = 1920, height: int = 1080) -> None:
    """Render a single frame to an image file."""
    points = get_frame_data(db, timestamp)
    logger.info(f"Rendering {len(points)} satellites at {timestamp.isoformat()}")

    if not points:
        logger.warning("No data for this timestamp")
        return

    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.set_facecolor("black")
    ax.set_facecolor("black")

    # Group by shell for color-coding and legend
    shells: dict[str | None, list[dict]] = {}
    for p in points:
        shells.setdefault(p["shell"], []).append(p)

    for shell, pts in sorted(shells.items(), key=lambda kv: kv[0] or ""):
        x = [p["co_raan"] for p in pts]
        y = [p["arg_lat"] for p in pts]
        color = SHELL_COLORS.get(shell or "", DEFAULT_COLOR)
        label = shell or "Unknown"
        ax.scatter(x, y, s=20, c=color, edgecolors="none", linewidths=0,
                   label=f"{label} ({len(pts)})", alpha=0.85)

    ax.set_xlim(0, 360)
    ax.set_ylim(360, 0)  # 0 at top, 360 at bottom
    ax.set_xlabel("Co-precessing Longitude of Ascending Node (°)", color="white")
    ax.set_ylabel("Anomaly Past Ascending Node (°)", color="white")
    ax.set_title(timestamp.strftime("%Y-%m-%d %H:%M UTC"), color="white", fontsize=14)

    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("white")

    ax.set_xticks(range(0, 361, 30))
    ax.set_yticks(range(0, 361, 30))
    ax.grid(True, alpha=0.15, color="white")

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08),
              ncol=min(len(shells), 5), fontsize=11, framealpha=0.3,
              facecolor="black", edgecolor="gray", labelcolor="white",
              markerscale=1.2)

    plt.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.13)
    plt.savefig(output_path, facecolor="black", dpi=dpi)
    plt.close()
    logger.info(f"Saved: {output_path}")
