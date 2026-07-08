from __future__ import annotations

from typing import Any

from .common import FetchError, get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    host = _host_from_token(ats_token)
    data = get_json(f"https://{host}/json")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _host_from_token(ats_token: str) -> str:
    host = ats_token.strip().lower()
    if not host.endswith(".breezy.hr"):
        raise FetchError(f"Invalid Breezy token: {ats_token}")
    return host
