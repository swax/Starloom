"""Space-Track.org API client with authentication and rate limiting."""

import logging
import time
from datetime import date, datetime, timedelta, timezone

import requests

from .. import config

logger = logging.getLogger(__name__)


class SpaceTrackError(Exception):
    pass


class SpaceTrackClient:
    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self._session = requests.Session()
        self._login_time: datetime | None = None
        self._last_request_time: float = 0.0

    def login(self) -> None:
        resp = self._session.post(config.LOGIN_URL, data={
            "identity": self._username,
            "password": self._password,
        })
        if resp.status_code != 200:
            raise SpaceTrackError(f"Login failed with status {resp.status_code}")

        # Check for login failure (200 but error message in body)
        if "Failed" in resp.text or "Invalid" in resp.text:
            raise SpaceTrackError(f"Login rejected: {resp.text[:200]}")

        self._login_time = datetime.now(timezone.utc)
        logger.info("Logged in to Space-Track")

    def _ensure_session(self) -> None:
        """Refresh session if approaching expiry, re-login if needed."""
        if self._login_time is None:
            self.login()
            return

        elapsed = (datetime.now(timezone.utc) - self._login_time).total_seconds() / 60
        if elapsed >= config.SESSION_REFRESH_MINUTES:
            logger.info("Session approaching expiry, refreshing...")
            try:
                resp = self._session.get(config.WHOAMI_URL)
                data = resp.json()
                if data.get("logged_in"):
                    self._login_time = datetime.now(timezone.utc)
                    logger.info("Session refreshed")
                    return
            except Exception:
                pass
            # Refresh failed, re-login
            logger.info("Session expired, re-logging in...")
            self.login()

    def _wait_for_rate_limit(self) -> None:
        """Ensure minimum interval between requests for even pacing."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        wait = config.MIN_REQUEST_INTERVAL_SECONDS - elapsed
        if wait > 0:
            logger.debug(f"Pacing: waiting {wait:.1f}s")
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    def query(self, url_path: str, max_retries: int = 3) -> list[dict]:
        """Execute a query against the Space-Track API with rate limiting and retries."""
        self._ensure_session()
        self._wait_for_rate_limit()

        url = f"{config.QUERY_URL}{url_path}"
        logger.debug(f"GET {url}")

        for attempt in range(max_retries):
            resp = self._session.get(url)

            if resp.status_code == 200:
                if not resp.text or resp.text.strip() == "":
                    return []
                return resp.json()

            if resp.status_code == 429:
                wait = 60 * (2 ** attempt)
                logger.warning(f"Rate limited (429), waiting {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                wait = 30 * (2 ** attempt)
                logger.warning(
                    f"Server error {resp.status_code}, waiting {wait}s "
                    f"(attempt {attempt + 1}): {resp.text[:200]}"
                )
                time.sleep(wait)
                continue

            raise SpaceTrackError(
                f"Query failed with status {resp.status_code}: {resp.text[:200]}"
            )

        raise SpaceTrackError(f"Query failed after {max_retries} retries")

    def fetch_starlink_catalog(self) -> list[dict]:
        """Get current catalog of all Starlink satellites (all shells, including decayed)."""
        return self.query(
            "/class/gp"
            "/OBJECT_NAME/STARLINK~~"
            "/orderby/NORAD_CAT_ID"
            "/format/json"
        )

    def fetch_gp_history_by_date(self, creation_date: str) -> list[dict]:
        """Fetch all GP history records created on a given date.

        Uses the CREATION_DATE one-day-at-a-time approach required by
        Space-Track.org — no per-object (NORAD_CAT_ID) filtering.
        Caller is responsible for filtering to satellites of interest.
        """
        next_day = (
            date.fromisoformat(creation_date) + timedelta(days=1)
        ).isoformat()
        return self.query(
            f"/class/gp_history"
            f"/CREATION_DATE/{creation_date}--{next_day}"
            f"/orderby/NORAD_CAT_ID,EPOCH asc"
            f"/format/json"
        )

    def close(self) -> None:
        try:
            self._session.get(config.LOGOUT_URL)
        except Exception:
            pass
        self._session.close()
        logger.info("Session closed")
