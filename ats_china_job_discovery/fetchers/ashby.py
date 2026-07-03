from __future__ import annotations

from typing import Any

from .common import get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{ats_token}"
    data = get_json(url)
    if isinstance(data, dict):
        jobs = data.get("jobs") or data.get("postings") or []
        return jobs if isinstance(jobs, list) else []
    return []
