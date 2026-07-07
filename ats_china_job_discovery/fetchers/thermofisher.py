from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import requests

from .common import FetchError, TIMEOUT_SECONDS, USER_AGENT


BASE_URL = "https://jobs.thermofisher.com"
WORKDAY_HOST = "thermofisher.wd5.myworkdayjobs.com"
WORKDAY_TENANT = "thermofisher"
WORKDAY_SITE = "ThermoFisherCareers"
PAGE_SIZE = 10
MAX_PAGES = 30
DETAIL_WORKERS = 6
TARGET_COUNTRIES = ("china", "japan", "germany")
RECENT_DAYS = 30
STALE_PAGE_LIMIT = 6


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    category_url = _category_url(ats_token)
    return _collect_recent_target_jobs(category_url)


def _category_url(ats_token: str) -> str:
    token = ats_token.strip("/")
    if not token:
        raise FetchError("Missing Thermo Fisher category token")
    return f"{BASE_URL}/{token}"


def _collect_recent_target_jobs(category_url: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    jobs: list[dict[str, Any]] = []
    stale_pages = 0

    for page_index in range(MAX_PAGES):
        offset = page_index * PAGE_SIZE
        page_url = category_url if offset == 0 else f"{category_url}?from={offset}&s=1"
        html = _get_text(page_url)
        links = _extract_workday_links(html)
        new_links = [link for link in links if link not in seen]
        if not new_links:
            break

        for link in new_links:
            seen.add(link)
        target_links = [link for link in new_links if _matches_target_country(link)]
        if not target_links:
            stale_pages += 1
            if stale_pages >= STALE_PAGE_LIMIT:
                break
            continue

        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
            page_jobs = list(
                executor.map(lambda link: _fetch_detail(link, category_url), target_links)
            )

        recent_page_jobs = [
            job
            for job in page_jobs
            if _matches_detail_location(job) and _is_recent_posting(job)
        ]
        jobs.extend(recent_page_jobs)

        if recent_page_jobs:
            stale_pages = 0
        else:
            stale_pages += 1
            if stale_pages >= STALE_PAGE_LIMIT:
                break

    return jobs


def _extract_workday_links(html: str) -> list[str]:
    links = re.findall(
        r"https://thermofisher\.wd5\.myworkdayjobs\.com/[^\"'<>\s)]+",
        html,
    )
    return sorted(set(_clean_apply_url(link) for link in links if "/job/" in link))


def _fetch_detail(apply_url: str, category_url: str) -> dict[str, Any]:
    parsed = urlsplit(apply_url)
    external_path = parsed.path.removeprefix(f"/{WORKDAY_SITE}")
    external_path = external_path.removesuffix("/apply")
    detail_url = (
        f"https://{WORKDAY_HOST}/wday/cxs/{WORKDAY_TENANT}/{WORKDAY_SITE}"
        f"{external_path}"
    )
    raw = {
        "externalPath": external_path,
        "url": apply_url,
        "_thermofisher_category_url": category_url,
        "_workday_host": WORKDAY_HOST,
        "_workday_tenant": WORKDAY_TENANT,
        "_workday_site": WORKDAY_SITE,
    }

    try:
        detail = _get_json(detail_url)
    except FetchError as exc:
        raw["_workday_detail_error"] = str(exc)[:1000]
        return raw

    if isinstance(detail, dict):
        raw["_workday_detail"] = detail
    return raw


def _matches_target_country(link: str) -> bool:
    lowered = link.lower()
    return any(country in lowered for country in TARGET_COUNTRIES)


def _matches_detail_location(raw: dict[str, Any]) -> bool:
    detail = raw.get("_workday_detail")
    if not isinstance(detail, dict):
        return _matches_target_country(str(raw.get("url") or ""))

    posting_info = detail.get("jobPostingInfo")
    if not isinstance(posting_info, dict):
        return _matches_target_country(str(raw.get("url") or ""))

    location = " ".join(
        str(posting_info.get(key) or "")
        for key in ("location", "primaryLocation", "additionalLocationsText")
    ).lower()
    return any(country in location for country in TARGET_COUNTRIES)


def _is_recent_posting(raw: dict[str, Any]) -> bool:
    detail = raw.get("_workday_detail")
    if not isinstance(detail, dict):
        return False

    posting_info = detail.get("jobPostingInfo")
    if not isinstance(posting_info, dict):
        return False

    posted_on = str(posting_info.get("postedOn") or raw.get("postedOn") or "").strip()
    if not posted_on:
        return False

    age_days = _posted_on_age_days(posted_on)
    if age_days is None:
        return False

    raw["_thermofisher_posted_age_days"] = age_days
    return age_days <= RECENT_DAYS


def _posted_on_age_days(posted_on: str) -> int | None:
    value = posted_on.strip().lower()
    if "30+" in value:
        return RECENT_DAYS + 1
    if "today" in value:
        return 0
    if "yesterday" in value:
        return 1

    match = re.search(r"(\d+)\s+days?\s+ago", value)
    if match:
        return int(match.group(1))

    for date_format in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            posted_date = datetime.strptime(posted_on.strip(), date_format).date()
        except ValueError:
            continue
        today = datetime.now(timezone.utc).date()
        return max(0, (today - posted_date).days)

    return None


def _clean_apply_url(url: str) -> str:
    return url.split("?")[0].split("#")[0]


def _get_text(url: str) -> str:
    try:
        response = _request("GET", url, accept="text/html")
    except requests.RequestException as exc:
        raise FetchError(str(exc)) from exc
    return response.text


def _get_json(url: str) -> Any:
    try:
        response = _request("GET", url, accept="application/json")
        return response.json()
    except requests.RequestException as exc:
        raise FetchError(str(exc)) from exc
    except ValueError as exc:
        raise FetchError(f"Invalid JSON response from {url}") from exc


def _request(method: str, url: str, *, accept: str) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    response = session.request(
        method,
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response
