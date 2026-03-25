# Starloom

Data acquisition and visualization pipeline for the Starlink satellite constellation, built on orbital data from [Space-Track.org](https://www.space-track.org).

Inspired by [Elias Eccli's excellent Starlink constellation animation videos](https://www.youtube.com/watch?v=rddTXl_7Wr8). This project aims to create an updated version covering the full constellation across all orbital shells.

Downloads historical GP (General Perturbations) data for all ~11,000+ Starlink satellites across every orbital shell, from the first launch in May 2019 through today, and renders constellation visualizations in a co-precessing orbital frame.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd starloom
uv sync
```

### Space-Track Credentials

You need a free account at [space-track.org](https://www.space-track.org/auth/createAccount).

```bash
cp .env.example .env
# Edit .env with your credentials
```

### Import Launch Data

The launch/shell mapping comes from `data/launches.xlsx`. Import it after setup and whenever the file is updated:

```bash
uv run starloom import-launches data/launches.xlsx
```

This links each satellite to its mission and shell (Gen1 Shell 1, Gen2 Shell 2, etc.) via COSPAR ID matching.

## Downloading Data

Historical orbital data can come from two sources: **bulk TLE files** (preferred for historical data) and the **Space-Track API** (for recent data only). The `fetch` command handles both automatically.

### Step 1: Download Bulk TLE Files

Space-Track provides yearly TLE archives covering all tracked objects. These are the recommended way to get historical data — the `gp_history` API is intended for small, ad-hoc queries only.

> **Warning:** Space-Track will suspend your account if you make excessive `gp_history` API requests, even at compliant request rates. Always use bulk files for historical data.

1. Download the yearly `.txt` files from Space-Track's cloud storage:
   https://ln5.sync.com/dl/afd354190/c5cd2q72-a5qjzp4q-nbjdiqkr-cenajuqu
2. Place them in `data/bulk/` (create the directory if needed)

```bash
mkdir -p data/bulk
# Download tle2019.txt through tle2025.txt (or current year) into data/bulk/
```

### Step 2: Populate the Satellite Catalog

The catalog tells starloom which NORAD IDs are Starlink satellites, so it can filter the bulk files (which contain all satellites).

```bash
uv run starloom catalog
```

### Step 3: Fetch

The `fetch` command will:
1. Refresh the satellite catalog (falls back to existing data if the API is unavailable)
2. Import any bulk TLE files found in `data/bulk/`
3. Calculate remaining gaps between the bulk data and today
4. **Ask for confirmation** before making any API requests, showing the request count and estimated time

```bash
# See what would happen without doing anything
uv run starloom fetch --dry-run

# Run the full pipeline (bulk import + API gap-fill)
uv run starloom fetch

# Fetch a specific date range via API only
uv run starloom fetch --start-date 2024-01-01 --end-date 2024-02-01

# Point to a different bulk file directory
uv run starloom fetch --bulk-dir /path/to/tle/files

# Verbose logging
uv run starloom -v fetch
```

API requests are paced at one every 18 seconds (~200/hr, well under the 30/min and 300/hr limits). Ctrl+C is safe — progress is saved and the next run resumes where it left off.

### Verifying Bulk Data

To confirm that bulk TLE files produce the same data as the API, you can run a comparison against existing API records:

```bash
uv run starloom verify-bulk data/bulk/tle2021.txt
```

This parses the bulk file, matches records against API data by satellite ID and epoch, and compares all orbital elements. Nothing is inserted — it's a read-only check.

### Importing Bulk Files Directly

You can also import bulk files without running the full fetch pipeline:

```bash
uv run starloom import-bulk data/bulk/
```

## Rendering

Generate a constellation visualization for any timestamp that has data:

```bash
# Render all shells (default 1920x1080)
uv run starloom render 2026-03-12 -o frame.png

# 4K output
uv run starloom render 2026-03-12 -o frame_4k.png --width 3840 --height 2160

# Filter to a specific inclination (43°, 53°, 70°, or 97°)
uv run starloom render 2026-03-12 --inclination 53 -o frame_53deg.png
```

### Other Commands

```bash
# Check fetch progress
uv run starloom status

# Browse the satellite catalog
uv run starloom catalog
```

## How the Visualization Works

Each frame plots every satellite's position in orbital element space:

- **X axis**: Co-precessing longitude of the ascending node (RAAN with J2 precession removed)
- **Y axis**: Anomaly past the ascending node (argument of perigee + mean anomaly, propagated to the target timestamp)

### Co-precessing Frame

Earth's oblateness (J2) causes orbital planes to precess — the RAAN drifts over time. To keep orbital planes stationary in the plot, we subtract each satellite's expected precession rate based on its actual inclination. When `--inclination` is specified, all satellites use that single reference rate; otherwise each satellite uses its own inclination for the correction.

### Mean Anomaly Propagation

TLEs are generated at different times for different satellites. To show all satellites at the same instant, we propagate each satellite's mean anomaly forward from its TLE epoch to the target timestamp using its mean motion.

### Coloring

- Dots are colored by **actual measured inclination**: blue (53°), gold (43°), orange (70°), purple (97°)
- The legend shows **shell names** from the launch data with satellite counts
- **Operational satellites** (altitude > 350km) are bright; transitioning satellites (raising orbit or deorbiting) are dimmed

## Data

- `data/launches.xlsx` — Launch missions with shell assignments, COSPAR IDs, and dates. Checked into git.
- `data/bulk/` — Directory for bulk TLE text files downloaded from Space-Track's cloud storage. Gitignored.
- `data/starloom.db` — SQLite database with satellite catalog, GP history, and fetch progress. Gitignored; rebuild with `starloom fetch`.

## Project Structure

```
src/starloom/
    cli.py               # Command-line interface
    config.py             # Constants and rate limit settings
    database.py           # SQLite schema and operations
    import_launches.py    # Launch xlsx import and satellite-to-launch linking
    render.py             # Frame rendering with matplotlib
    api/
        client.py         # Space-Track API client with auth and rate limiting
        fetcher.py        # Fetch orchestrator (bulk import + API gap-fill)
    bulk/
        tle_parser.py     # TLE two/three-line element text parser
        importer.py       # Bulk TLE file import (zip/txt)
        verify.py         # Verify bulk data against API records
```
