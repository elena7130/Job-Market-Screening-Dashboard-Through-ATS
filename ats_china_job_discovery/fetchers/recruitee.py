from __future__ import annotations

from typing import Any

from .common import get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    url = f"https://{ats_token}.recruitee.com/api/offers/"
    data = get_json(url)
    if isinstance(data, dict):
        offers = data.get("offers") or data.get("jobs") or []
        return offers if isinstance(offers, list) else []
    if isinstance(data, list):
        return data
    return []
