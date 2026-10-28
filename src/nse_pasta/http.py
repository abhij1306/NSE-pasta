"""The one polite HTTP client: browser-like session, cookie warm-up, pacing and retries.

NSE's website JSON endpoints (`www.nseindia.com/api/...`) answer only a session that first
loaded the page they belong to (it sets cookies) and sends a browser User-Agent and that page as
Referer. The archive host (`nsearchives.nseindia.com`) needs the headers but no cookies. These
endpoints are not a documented public API: keep the pace slow (one request every 2 seconds by
default), never run two pulls at once, and respect NSE's terms of use.

screener.in gets its own client: public pages only, no cookies, no login, one request every 3
seconds by default (`config.Screener`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 2.0  # seconds between two request starts
DEFAULT_TRIES = 4
DEFAULT_TIMEOUT = 60.0
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "Accept": "application/json, text/plain, text/csv, application/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
RETRY_STATUSES = frozenset({401, 403, 429})  # blocked for now: back off, new cookies, ask again
BACKOFF = (5.0, 20.0, 60.0)  # seconds before the 2nd, 3rd and 4th try


@dataclass(frozen=True)
class Fetched:
    """One final answer: `status` is the HTTP status, or 0 when no answer came at all."""

    status: int
    body: bytes = b""

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.body)


def transient(status: int) -> bool:
    """A failure worth asking again on a later run (no answer, blocked, a server error): never
    cached as final."""
    return status == 0 or status in RETRY_STATUSES or status >= 500


class Client:
    """Paced GETs with retries. `get` never raises on HTTP or network errors.

    `referer` names the page a JSON endpoint belongs to: it is loaded once per session for
    cookies and sent as the Referer. None sends neither (archives, screener.in)."""

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL,
        tries: int = DEFAULT_TRIES,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = USER_AGENT,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self.tries = tries
        self.timeout = timeout
        self.headers = HEADERS | {"User-Agent": user_agent}
        self.sleep = sleep
        self.requests = 0
        self.statuses: dict[int, int] = {}
        self._last = 0.0
        self._client: httpx.Client | None = None
        self._warm: set[str] = set()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._warm.clear()  # the cookies went with the session

    def _session(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers=self.headers, timeout=self.timeout, follow_redirects=True
            )
        return self._client

    def _pace(self) -> None:
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        self._last = time.monotonic()

    def _warm_up(self, page: str) -> None:
        """Load `page` once so the session holds NSE's cookies for its endpoints."""
        self._pace()
        self.requests += 1
        try:
            self._session().get(page, headers={"Accept": "text/html"})
        except httpx.HTTPError as exc:
            logger.warning("warm-up %s failed: %s", page, type(exc).__name__)
        self._warm.add(page)

    def get(
        self, url: str, params: dict[str, str] | None = None, referer: str | None = None
    ) -> Fetched:
        """The final answer for `url`: a 200, a 404 or other final status, or the last
        transient one after `tries` (backing off; a 401/403 loads the referer page again)."""
        got = Fetched(0)
        for attempt in range(self.tries):
            if attempt:
                self.sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
                if got.status in (401, 403) and referer:
                    self.close()  # a fresh session: new cookies
            got = self._once(url, params, referer)
            if not transient(got.status):
                return got
            logger.warning("try %d %s: HTTP %s", attempt + 1, url, got.status or "no answer")
        return got

    def _once(self, url: str, params: dict[str, str] | None, referer: str | None) -> Fetched:
        if referer and referer not in self._warm:
            self._warm_up(referer)
        self._pace()
        self.requests += 1
        headers = {"Referer": referer} if referer else {}
        try:
            response = self._session().get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("%s: %s", url, type(exc).__name__)
            return Fetched(0)
        self.statuses[response.status_code] = self.statuses.get(response.status_code, 0) + 1
        return Fetched(response.status_code, response.content)
