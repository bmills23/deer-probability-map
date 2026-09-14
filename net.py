"""Shared HTTP session: browser-like headers + retry/backoff. Several of
this project's free public APIs (Overpass in particular) reject or
rate-limit requests carrying the default python-requests User-Agent, or
hiccup transiently under load -- retrying almost always works. Same
pattern as striper-run-tracker's _make_session."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (compatible; elk-probability-map/1.0; "
    "+https://github.com/bryanmills/elk-probability-map)"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json, image/png, */*"}


def make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    retry = Retry(total=5, connect=3, read=3, status=5,
                  status_forcelist=(403, 406, 408, 425, 429, 500, 502, 503, 504),
                  backoff_factor=1.5, raise_on_status=False,
                  allowed_methods=frozenset(["GET", "POST"]))
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


SESSION = make_session()
