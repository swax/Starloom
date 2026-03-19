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

## Usage

### Download data

The `fetch` command discovers all Starlink satellites, then downloads their orbital history into a local SQLite database (`data/starloom.db`). Requests are paced at one every 18 seconds to stay within API rate limits.

```bash
# See how many batches are needed without fetching
uv run starloom fetch --dry-run

# Start fetching (Ctrl+C safe — resumes where it left off)
uv run starloom fetch

# Fetch a specific date range (useful for testing)
uv run starloom fetch --start-date 2024-01-01 --end-date 2024-02-01

# Verbose logging
uv run starloom -v fetch
```

The fetcher iterates by date window first, then satellite batch, so you get coverage across all satellites early rather than deep history for a few. Satellites are grouped by launch date to skip date ranges before each satellite existed. A full fetch is ~34,000 requests (~170 hours), spread across as many sessions as you like.

### Render a frame

Generate a constellation visualization for any timestamp that has data:

```bash
# Render all shells (default 1920x1080)
uv run starloom render 2026-03-12 -o frame.png

# 4K output
uv run starloom render 2026-03-12 -o frame_4k.png --width 3840 --height 2160

# Filter to a specific inclination (43°, 53°, 70°, or 97°)
uv run starloom render 2026-03-12 --inclination 53 -o frame_53deg.png
```

### Other commands

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
- `data/starloom.db` — SQLite database with satellite catalog, GP history, and fetch progress. Gitignored; rebuild with `starloom fetch`.

## Project Structure

```
src/starloom/
    cli.py               # Command-line interface
    config.py             # Constants and rate limit settings
    database.py           # SQLite schema and operations
    fetcher.py            # Batch download orchestrator
    import_launches.py    # xlsx import and satellite-to-launch linking
    render.py             # Frame rendering with matplotlib
    spacetrack_client.py  # API client with auth and rate limiting
```
