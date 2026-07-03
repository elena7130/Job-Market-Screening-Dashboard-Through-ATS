from __future__ import annotations

from typing import Any

from .common import get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{ats_token}/jobs"
    data = get_json(url, params={"content": "true"})
    return data.get("jobs", []) if isinstance(data, dict) else []
