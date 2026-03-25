"""Centralized configuration and constants."""

BASE_URL = "https://www.space-track.org"
LOGIN_URL = f"{BASE_URL}/ajaxauth/login"
LOGOUT_URL = f"{BASE_URL}/ajaxauth/logout"
WHOAMI_URL = f"{BASE_URL}/app/data/whoami"
QUERY_URL = f"{BASE_URL}/basicspacedata/query"

DEFAULT_DB_PATH = "data/starloom.db"
DEFAULT_BULK_DIR = "data/bulk"

# Rate limits: <30 requests/minute, <300 requests/hour.
# We pace at 1 request/minute to be conservative. Worst case of a
# full year catch-up (365 days) takes ~6 hours. Each query fetches
# a full day of data, so normal daily keeping-up is just 1 request.
# GP catalog (class/gp) has a separate limit of 1 query/hour.
MIN_REQUEST_INTERVAL_SECONDS = 60

# Session expires after 2 hours; refresh proactively at 100 minutes
SESSION_REFRESH_MINUTES = 100

# Bulk TLE files cover everything before this date.
# API queries (by CREATION_DATE) start from here.
API_START_DATE = "2026-01-01"
