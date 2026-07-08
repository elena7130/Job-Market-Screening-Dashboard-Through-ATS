from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .common import FetchError, get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    api_url = _api_url(ats_token)
    data = get_json(api_url)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _api_url(ats_token: str) -> str:
    parsed = urlparse(ats_token.strip())
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.comeet.co"
        or not parsed.path.startswith("/careers-api/")
    ):
        raise FetchError(f"Invalid Comeet token: {ats_token}")
    return ats_token.strip()
