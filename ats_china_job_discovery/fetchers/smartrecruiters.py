from __future__ import annotations

import os
from typing import Any

from .common import FetchError, get_json


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    all_jobs: list[dict[str, Any]] = []
    limit = 100
    offset = 0

    while True:
        url = f"https://api.smartrecruiters.com/v1/companies/{ats_token}/postings"
        data = get_json(url, params={"limit": limit, "offset": offset})
        if not isinstance(data, dict):
            break

        jobs = data.get("content") or data.get("postings") or []
        if not isinstance(jobs, list) or not jobs:
            break

        if should_fetch_details():
            all_jobs.extend(_with_details(ats_token, jobs))
        else:
            all_jobs.extend(jobs)
        if len(jobs) < limit:
            break
        offset += limit

    return all_jobs


def should_fetch_details() -> bool:
    return os.getenv("SMARTRECRUITERS_FETCH_DETAILS", "").lower() in {"1", "true", "yes"}


def _with_details(ats_token: str, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    detailed_jobs: list[dict[str, Any]] = []
    for job in jobs:
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            detailed_jobs.append(job)
            continue
        detail_url = (
            f"https://api.smartrecruiters.com/v1/companies/{ats_token}/postings/{job_id}"
        )
        try:
            detail = get_json(detail_url)
            detailed_jobs.append(detail if isinstance(detail, dict) else job)
        except FetchError:
            detailed_jobs.append(job)
    return detailed_jobs
