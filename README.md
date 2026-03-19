# Starloom

Data acquisition and visualization pipeline for the Starlink satellite constellation, built on orbital data from [Space-Track.org](https://www.space-track.org).

Downloads historical GP (General Perturbations) data for all ~11,000+ Starlink satellites across every orbital shell, from the first launch in May 2019 through today.

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

## Usage

### Download data

The `fetch` command discovers all Starlink satellites, then downloads their orbital history into a local SQLite database. Requests are paced at one every 18 seconds to stay within API rate limits.

```bash
# See how many batches are needed without fetching
uv run starloom fetch --dry-run

# Start fetching (Ctrl+C safe — resumes where it left off)
uv run starloom fetch

# Verbose logging
uv run starloom -v fetch
```

Satellites are sorted by launch date so the fetcher only queries date ranges after each satellite existed, cutting total requests significantly. A full fetch is ~34,000 requests (~170 hours), spread across as many sessions as you like.

### Check progress

```bash
uv run starloom status
```

### Browse the catalog

```bash
uv run starloom catalog
```

## Project Structure

```
src/starloom/
    cli.py               # Command-line interface
    config.py             # Constants and rate limit settings
    database.py           # SQLite schema and operations
    fetcher.py            # Batch download orchestrator
    spacetrack_client.py  # API client with auth and rate limiting
```
