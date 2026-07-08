from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from .common import FetchError, get_json


DEFAULT_MAX_PAGES = 50
DEFAULT_PAGE_SIZE = 10


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    api_url = _api_url(ats_token)
    first = get_json(api_url)
    jobs = _jobs(first)
    total = _int_value(first.get("totalCount")) if isinstance(first, dict) else 0
    page_size = len(jobs) or _int_value(first.get("count")) if isinstance(first, dict) else 0
    page_size = page_size or DEFAULT_PAGE_SIZE

    if total > page_size:
        pages = min(DEFAULT_MAX_PAGES, (total + page_size - 1) // page_size)
        for page in range(2, pages + 1):
            try:
                data = get_json(_with_page(api_url, page))
            except FetchError:
                break
            jobs.extend(_jobs(data))
    return jobs


def _api_url(ats_token: str) -> str:
    parsed = urlparse(ats_token.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise FetchError(f"Invalid JibeApply token: {ats_token}")
    return ats_token.strip()


def _with_page(url: str, page: int) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _jobs(data: Any) -> list[dict[str, Any]]:
    rows = data.get("jobs") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
