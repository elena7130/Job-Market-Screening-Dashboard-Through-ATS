from __future__ import annotations

from typing import Any

from .common import get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    url = f"https://api.lever.co/v0/postings/{ats_token}"
    data = get_json(url, params={"mode": "json"})
    return data if isinstance(data, list) else []
