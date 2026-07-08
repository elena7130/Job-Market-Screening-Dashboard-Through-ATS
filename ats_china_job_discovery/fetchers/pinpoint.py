from __future__ import annotations

from typing import Any

from .common import FetchError, get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    host = _host_from_token(ats_token)
    data = get_json(f"https://{host}/postings.json")
    rows = data.get("data") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _host_from_token(ats_token: str) -> str:
    host = ats_token.strip().lower()
    if not host.endswith(".pinpointhq.com"):
        raise FetchError(f"Invalid Pinpoint token: {ats_token}")
    return host
