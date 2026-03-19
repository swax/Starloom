"""Centralized configuration and constants."""

BASE_URL = "https://www.space-track.org"
LOGIN_URL = f"{BASE_URL}/ajaxauth/login"
LOGOUT_URL = f"{BASE_URL}/ajaxauth/logout"
WHOAMI_URL = f"{BASE_URL}/app/data/whoami"
QUERY_URL = f"{BASE_URL}/basicspacedata/query"

DEFAULT_DB_PATH = "data/starloom.db"

# Rate limits (actual: 30/min, 300/hr)
# We pace evenly at 200/hr = 1 request per 18 seconds, which also stays
# well under the 30/min limit (~3.3/min).
MIN_REQUEST_INTERVAL_SECONDS = 18

# Session expires after 2 hours; refresh proactively at 100 minutes
SESSION_REFRESH_MINUTES = 100

# Batch parameters for GP_HISTORY fetching
NORAD_IDS_PER_BATCH = 100
EPOCH_DAYS_PER_BATCH = 3
