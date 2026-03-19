"""
Test script to verify Space-Track API connectivity and pull sample Starlink data.

Pulls the latest GP (general perturbations) data for a small set of Starlink
satellites to validate credentials and API access.
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.space-track.org"
LOGIN_URL = f"{BASE_URL}/ajaxauth/login"
QUERY_URL = f"{BASE_URL}/basicspacedata/query"


def login(session: requests.Session) -> None:
    username = os.environ.get("SPACETRACK_USERNAME")
    password = os.environ.get("SPACETRACK_PASSWORD")

    if not username or not password:
        print("Error: Set SPACETRACK_USERNAME and SPACETRACK_PASSWORD in .env")
        sys.exit(1)

    resp = session.post(LOGIN_URL, data={
        "identity": username,
        "password": password,
    })
    resp.raise_for_status()
    print(f"Login response: {resp.status_code}")


def fetch_starlink_sample(session: requests.Session) -> list[dict]:
    """Fetch latest GP data for first 20 Starlink satellites (small test query)."""
    url = (
        f"{QUERY_URL}/class/gp"
        f"/OBJECT_NAME/STARLINK~~"
        f"/INCLINATION/52.5--53.5"       # 53° shell
        f"/MEAN_MOTION/14.9--15.3"       # ~550km altitude range
        f"/decay_date/null-val"           # still in orbit
        f"/orderby/NORAD_CAT_ID"
        f"/limit/20"
        f"/format/json"
    )
    resp = session.get(url)
    resp.raise_for_status()
    return resp.json()


def print_summary(satellites: list[dict]) -> None:
    print(f"\nRetrieved {len(satellites)} satellites:\n")
    print(f"{'NORAD_ID':>10}  {'NAME':<25}  {'EPOCH':<22}  {'INC':>6}  {'ALT_km':>8}")
    print("-" * 80)

    GM = 398600441800000.0
    MRAD = 6378.137
    import math

    for sat in satellites:
        norad_id = sat["NORAD_CAT_ID"]
        name = sat["OBJECT_NAME"]
        epoch = sat["EPOCH"]
        inc = float(sat["INCLINATION"])
        mm = float(sat["MEAN_MOTION"])
        ecc = float(sat["ECCENTRICITY"])

        # Derive altitude from mean motion
        sma = (GM ** (1/3)) / ((2 * math.pi * mm / 86400) ** (2/3)) / 1000
        alt = sma * (1 - ecc) - MRAD  # periapsis altitude

        print(f"{norad_id:>10}  {name:<25}  {epoch:<22}  {inc:>6.2f}  {alt:>8.1f}")


def main():
    with requests.Session() as session:
        print("Logging in to Space-Track...")
        login(session)

        print("Fetching sample Starlink GP data (53° shell, limit 20)...")
        satellites = fetch_starlink_sample(session)

        if not satellites:
            print("No data returned. Check credentials and query.")
            sys.exit(1)

        print_summary(satellites)

        # Also dump raw JSON for inspection
        with open("sample_output.json", "w") as f:
            json.dump(satellites, f, indent=2)
        print(f"\nRaw JSON saved to sample_output.json")


if __name__ == "__main__":
    main()
