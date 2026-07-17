from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import html
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .common import FetchError, TIMEOUT_SECONDS, USER_AGENT


DETAIL_WORKERS = 6
PAGE_SIZE = 10


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    host, options = _parse_token(ats_token)
    endpoint = f"https://{host}/services/recruiting/v1/jobs"
    locale = options.get("locale", "en_GB")
    location = options.get("location", "")

    session = requests.Session()
    session.trust_env = False
    jobs: list[dict[str, Any]] = []
    page_number = 0
    total: int | None = None

    while total is None or page_number * PAGE_SIZE < total:
        data = _post_jobs(session, endpoint, locale, location, page_number)
        if not isinstance(data, dict):
            break

        total_value = data.get("totalJobs")
        if total is None:
            total = total_value if isinstance(total_value, int) else 0

        results = data.get("jobSearchResult") or []
        if not isinstance(results, list) or not results:
            break

        for item in results:
            if not isinstance(item, dict):
                continue
            response = item.get("response")
            if isinstance(response, dict):
                jobs.append(_from_response(host, locale, response))

        page_number += 1

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        details = list(executor.map(_fetch_detail, [job["url"] for job in jobs]))

    return [{**job, **detail} for job, detail in zip(jobs, details)]


def _parse_token(ats_token: str) -> tuple[str, dict[str, str]]:
    parts = ats_token.split("|")
    if not parts or not parts[0]:
        raise FetchError(f"Invalid SuccessFactors unified token: {ats_token}")
    options: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key and value:
            options[key] = value
    return parts[0], options


def _post_jobs(
    session: requests.Session, endpoint: str, locale: str, location: str, page_number: int
) -> dict[str, Any]:
    payload = {
        "keywords": "",
        "locale": locale,
        "location": location,
        "pageNumber": page_number,
        "sortBy": "recent",
    }
    try:
        response = session.post(
            endpoint,
            json=payload,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as direct_exc:
        proxy_session = requests.Session()
        proxy_session.trust_env = True
        try:
            response = proxy_session.post(
                endpoint,
                json=payload,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as proxy_exc:
            raise FetchError(
                f"Direct request failed: {direct_exc}; proxy retry also failed: {proxy_exc}"
            ) from proxy_exc

    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise FetchError(f"Invalid JSON response from {endpoint}") from exc


def _from_response(host: str, locale: str, response: dict[str, Any]) -> dict[str, Any]:
    job_id = str(response.get("id") or "").strip()
    title = _first(response.get("unifiedStandardTitle"), response.get("title"))
    url_title = _first(response.get("unifiedUrlTitle"), response.get("urlTitle"))
    if not url_title:
        url_title = quote(str(title or "untitled").replace(" ", "-"), safe=",-()")
    url = f"https://{host}/job/{url_title}/{job_id}-{locale}"

    return {
        "company_name": _company_name(host),
        "ats_job_id": job_id,
        "title": title,
        "location": _location(response),
        "department": _list_text(response.get("mfield1")),
        "date_posted": response.get("unifiedStandardStart"),
        "date_updated": response.get("unifiedStandardEnd"),
        "url": url,
        "raw_response": response,
    }


def _fetch_detail(url: str) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as direct_exc:
        proxy_session = requests.Session()
        proxy_session.trust_env = True
        try:
            response = proxy_session.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as proxy_exc:
            return {"description": "", "detail_error": f"{direct_exc}; {proxy_exc}"[:1000]}

    soup = BeautifulSoup(response.text, "html.parser")
    description = (
        soup.select_one('[itemprop="description"]')
        or soup.select_one(".jobdescription")
        or soup.select_one(".job-description")
    )
    return {"description": str(description) if description is not None else ""}


def _location(response: dict[str, Any]) -> str:
    values = [
        _list_text(response.get("jobLocationShort")),
        _list_text(response.get("jobLocationCity")),
        _list_text(response.get("jobLocationCountry")),
    ]
    return "; ".join(value for value in values if value)


def _list_text(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(str(item).strip() for item in value if str(item or "").strip())
    if value is None:
        return ""
    return str(value).strip()


def _first(*values: object) -> str:
    for value in values:
        text = html.unescape(str(value or "")).strip()
        if text:
            return text
    return ""


def _company_name(host: str) -> str:
    known_hosts = {
        "jobs.standardchartered.com": "Standard Chartered",
    }
    return known_hosts.get(host, host.split(".", 1)[0].replace("-", " ").title())
