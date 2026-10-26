"""Polite HTTP helpers shared by all state sources."""

from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("tracker.http")

USER_AGENT = (
    "Mozilla/5.0 (compatible; future-of-democracy-tracker/1.0; "
    "+https://github.com/MoveBeyondFPTP/Future-of-democracy)"
)


class Client:
    """requests.Session with retries, timeouts and a minimum delay between
    requests to the same host, so we never hammer a legislature's servers."""

    def __init__(self, delay: float = 0.25, timeout: int = 60, verify: bool = True):
        self.s = requests.Session()
        retry = Retry(
            total=4,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            respect_retry_after_header=True,
        )
        self.s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        self.s.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        self.s.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self.timeout = timeout
        self.verify = verify
        self._last = 0.0
        self.count = 0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def get(self, url: str, **kw) -> requests.Response:
        self._wait()
        kw.setdefault("timeout", self.timeout)
        kw.setdefault("verify", self.verify)
        self.count += 1
        r = self.s.get(url, **kw)
        return r

    def get_json(self, url: str, **kw):
        r = self.get(url, headers={"Accept": "application/json"}, **kw)
        r.raise_for_status()
        return r.json()

    def get_text(self, url: str, **kw) -> str:
        r = self.get(url, **kw)
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text
