# Space-Track.org API Reference (Project-Relevant Subset)

Full docs: https://www.space-track.org/documentation

## Authentication

POST credentials to get a session cookie (valid 2 hours):
```
POST https://www.space-track.org/ajaxauth/login
Body: identity=USERNAME&password=PASSWORD
```

Extend cookie lifetime by 2 more hours:
```
GET https://www.space-track.org/app/data/whoami
Returns: { "logged_in": true/false, "identity": "...", "session_expiration": "..." }
```

Logout:
```
GET https://www.space-track.org/ajaxauth/logout
```

## Rate Limits

- **30 requests per minute, 300 requests per hour**
- **GP (current TLEs):** max 1 query/hour, randomize the minute
- **GP_HISTORY:** Query by CREATION_DATE, one day at a time. Do NOT query by individual NORAD_CAT_ID.
- Pre-2026 data: use bulk TLE zip files from Space-Track's cloud storage.

## API Classes We Use

### GP (current orbital elements)
Latest element set per satellite. We use this for catalog discovery.
```
GET /basicspacedata/query/class/gp/OBJECT_NAME/STARLINK~~/orderby/NORAD_CAT_ID/format/json
```

### GP_HISTORY (historical orbital elements)
Query one day at a time by CREATION_DATE. Do not filter by NORAD_CAT_ID — filter client-side instead.
```
GET /basicspacedata/query/class/gp_history/CREATION_DATE/2026-01-01--2026-01-02/orderby/NORAD_CAT_ID,EPOCH asc/format/json
```

Each day's query only needs to run once — Space-Track does not insert TLEs retroactively.

## REST Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `>` | Greater than (alt: `%3E`) | `EPOCH/>2024-01-01` |
| `<` | Less than (alt: `%3C`) | |
| `<>` | Not equal (alt: `%3C%3E`) | |
| `,` | Comma-delimited OR | `NORAD_CAT_ID/25544,25545` |
| `--` | Inclusive range | `epoch/2024-01-01--2024-01-03` |
| `null-val` | NULL value | `decay_date/null-val` |
| `~~` | Wildcard/like | `OBJECT_NAME/STARLINK~~` |
| `now` | Current date/time | `EPOCH/>now-7` |

## Key REST Predicates

| Predicate | Description |
|-----------|-------------|
| `class/NAME` | Required. Data class to query |
| `format/json` | Response format (json, csv, xml, tle, 3le) |
| `orderby/COL asc` | Sort order |
| `limit/N` | Max records to return |
| `predicates/c1,c2` | Columns to return (default: all) |

## GP/GP_HISTORY Fields We Store

NORAD_CAT_ID, OBJECT_NAME, OBJECT_ID, EPOCH, MEAN_MOTION, ECCENTRICITY,
INCLINATION, RA_OF_ASC_NODE, ARG_OF_PERICENTER, MEAN_ANOMALY, BSTAR,
SEMIMAJOR_AXIS, PERIOD, APOAPSIS, PERIAPSIS, LAUNCH_DATE, DECAY_DATE,
TLE_LINE0/1/2, GP_ID, and others.
