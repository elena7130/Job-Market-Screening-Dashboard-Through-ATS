from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .common import FetchError, get_json


DETAIL_WORKERS = 8


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    host = _host_from_token(ats_token)
    origin = f"https://{host}"
    data = get_json(f"{origin}/careers/list")
    rows = data.get("result") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []

    jobs = [dict(row) for row in rows if isinstance(row, dict)]
    with ThreadPoolExecutor(max_workers=max(1, min(DETAIL_WORKERS, len(jobs) or 1))) as executor:
        details = list(executor.map(lambda row: _detail(origin, row), jobs))

    for job, detail in zip(jobs, details):
        job["_bamboohr_origin"] = origin
        job["_bamboohr_host"] = host
        if isinstance(detail, dict):
            job["_bamboohr_detail"] = detail
    return jobs


def _host_from_token(ats_token: str) -> str:
    host = ats_token.strip().lower()
    if not host.endswith(".bamboohr.com"):
        raise FetchError(f"Invalid BambooHR token: {ats_token}")
    return host


def _detail(origin: str, row: dict[str, Any]) -> dict[str, Any] | None:
    job_id = str(row.get("id") or "").strip()
    if not job_id:
        return None
    try:
        return get_json(f"{origin}/careers/{job_id}/detail")
    except FetchError:
        return None
