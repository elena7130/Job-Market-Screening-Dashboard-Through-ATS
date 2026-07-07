from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote_plus

import requests

from .common import FetchError, TIMEOUT_SECONDS, USER_AGENT


PAGE_SIZE = 20
DETAIL_WORKERS = 6


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    host, tenant, site, options = _parse_token(ats_token)
    list_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    recent_days = _option_int(options, "recent_days")
    location_keywords = _option_list(options, "location_keywords")

    postings_to_detail: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None

    while total is None or offset < total:
        data = _post_json(
            list_url,
            {
                "appliedFacets": _applied_facets(options),
                "limit": PAGE_SIZE,
                "offset": offset,
                "searchText": "",
            },
        )
        if not isinstance(data, dict):
            break

        postings = data.get("jobPostings") or data.get("jobs") or []
        if not isinstance(postings, list) or not postings:
            break

        total_value = data.get("total")
        if total is None:
            total = total_value if isinstance(total_value, int) else len(postings)

        postings_to_detail.extend(
            posting
            for posting in postings
            if isinstance(posting, dict)
            and _matches_recent_filter(posting, recent_days)
        )

        offset += len(postings)

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        jobs = list(
            executor.map(
                lambda posting: _with_detail(host, tenant, site, posting),
                postings_to_detail,
            )
        )
    return [
        job
        for job in jobs
        if _matches_recent_filter(job, recent_days)
        and _matches_location_keywords(job, location_keywords)
    ]


def _with_detail(
    host: str, tenant: str, site: str, posting: dict[str, Any]
) -> dict[str, Any]:
    raw = dict(posting)
    raw["_workday_host"] = host
    raw["_workday_tenant"] = tenant
    raw["_workday_site"] = site

    external_path = posting.get("externalPath")
    if not external_path:
        return raw

    detail_path = external_path if str(external_path).startswith("/") else f"/{external_path}"
    detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{detail_path}"

    try:
        detail = _get_json(detail_url)
    except FetchError as exc:
        raw["_workday_detail_error"] = str(exc)[:1000]
        return raw

    if isinstance(detail, dict):
        raw["_workday_detail"] = detail
    return raw


def _parse_token(ats_token: str) -> tuple[str, str, str, dict[str, str]]:
    parts = ats_token.split("|")
    if len(parts) < 3 or not all(parts[:3]):
        raise FetchError(f"Invalid Workday token: {ats_token}")
    options: dict[str, str] = {}
    for part in parts[3:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key and value:
            options[key] = value
    return parts[0], parts[1], parts[2], options


def _applied_facets(options: dict[str, str]) -> dict[str, list[str]]:
    facets: dict[str, list[str]] = {}
    locations = _option_list(options, "locations")
    if locations:
        facets["locations"] = locations
    return facets


def _option_list(options: dict[str, str], key: str) -> list[str]:
    value = options.get(key, "")
    return [
        unquote_plus(item).strip()
        for item in value.split(",")
        if unquote_plus(item).strip()
    ]


def _option_int(options: dict[str, str], key: str) -> int | None:
    value = options.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _matches_recent_filter(raw: dict[str, Any], recent_days: int | None) -> bool:
    if recent_days is None:
        return True

    age_days = _posting_age_days(raw)
    return age_days is not None and age_days <= recent_days


def _posting_age_days(raw: dict[str, Any]) -> int | None:
    posted_on = raw.get("postedOn")
    detail = raw.get("_workday_detail")
    if not posted_on and isinstance(detail, dict):
        posting_info = detail.get("jobPostingInfo")
        if isinstance(posting_info, dict):
            posted_on = posting_info.get("postedOn")

    if not posted_on:
        return None

    value = str(posted_on).strip().lower()
    if "30+" in value:
        return 31
    if "today" in value:
        return 0
    if "yesterday" in value:
        return 1

    import re

    match = re.search(r"(\d+)\s+days?\s+ago", value)
    if match:
        return int(match.group(1))

    for date_format in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            posted_date = datetime.strptime(str(posted_on).strip(), date_format).date()
        except ValueError:
            continue
        today = datetime.now(timezone.utc).date()
        return max(0, (today - posted_date).days)

    return None


def _matches_location_keywords(raw: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True
    location_text = _location_text(raw).lower()
    return any(keyword.lower() in location_text for keyword in keywords)


def _location_text(raw: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("locationsText", "location"):
        value = raw.get(key)
        if value:
            parts.append(str(value))

    detail = raw.get("_workday_detail")
    if isinstance(detail, dict):
        posting_info = detail.get("jobPostingInfo")
        if isinstance(posting_info, dict):
            for key in ("location", "primaryLocation", "additionalLocationsText"):
                value = posting_info.get(key)
                if value:
                    parts.append(str(value))

    return " ".join(parts)


def _post_json(url: str, payload: dict[str, Any]) -> Any:
    try:
        return _request_json("POST", url, json=payload, trust_env=False)
    except requests.RequestException as direct_exc:
        try:
            return _request_json("POST", url, json=payload, trust_env=True)
        except requests.RequestException as proxy_exc:
            raise FetchError(
                f"Direct request failed: {direct_exc}; proxy retry also failed: {proxy_exc}"
            ) from proxy_exc
    except ValueError as exc:
        raise FetchError(f"Invalid JSON response from {url}") from exc


def _get_json(url: str) -> Any:
    try:
        return _request_json("GET", url, json=None, trust_env=False)
    except requests.RequestException as direct_exc:
        try:
            return _request_json("GET", url, json=None, trust_env=True)
        except requests.RequestException as proxy_exc:
            raise FetchError(
                f"Direct request failed: {direct_exc}; proxy retry also failed: {proxy_exc}"
            ) from proxy_exc
    except ValueError as exc:
        raise FetchError(f"Invalid JSON response from {url}") from exc


def _request_json(
    method: str, url: str, *, json: dict[str, Any] | None, trust_env: bool
) -> Any:
    session = requests.Session()
    session.trust_env = trust_env
    response = session.request(
        method,
        url,
        json=json,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
