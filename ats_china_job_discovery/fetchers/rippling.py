from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .common import FetchError, get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    slug = ats_token.strip()
    if not slug or "/" in slug or "\\" in slug:
        raise FetchError(f"Invalid Rippling token: {ats_token}")
    url = f"https://api.rippling.com/platform/api/ats/v1/board/{quote(slug)}/jobs"
    data = get_json(url)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]
