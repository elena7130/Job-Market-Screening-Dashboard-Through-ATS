from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .common import FetchError, TIMEOUT_SECONDS, USER_AGENT


DETAIL_WORKERS = 6


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    url = _url_from_token(ats_token)
    if "/job/" in url:
        return [_fetch_detail(url)]

    session = requests.Session()
    session.trust_env = True
    first_html = _get_text(session, url)
    page_urls = _listing_page_urls(first_html, url)
    list_jobs = _parse_listing_jobs(first_html, url)

    for page_url in page_urls[1:]:
        html = _get_text(session, page_url)
        list_jobs.extend(_parse_listing_jobs(html, page_url))

    seen_ids: set[str] = set()
    unique_jobs: list[dict[str, Any]] = []
    for job in list_jobs:
        job_id = str(job.get("ats_job_id") or "").strip()
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        unique_jobs.append(job)

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        details = list(executor.map(lambda job: _fetch_detail(job["url"]), unique_jobs))

    return [{**job, **_non_empty_values(detail)} for job, detail in zip(unique_jobs, details)]


def _url_from_token(ats_token: str) -> str:
    parts = ats_token.split("|", 1)
    if len(parts) != 2 or not all(parts):
        raise FetchError(f"Invalid SuccessFactors RMK token: {ats_token}")
    host, path_query = parts
    if not path_query.startswith("/"):
        path_query = f"/{path_query}"
    return f"https://{host}{path_query}"


def _listing_page_urls(html: str, first_url: str) -> list[str]:
    total = _total_results(html)
    page_size = _page_size(html)
    if total and page_size:
        return [_page_url(first_url, startrow) for startrow in range(0, total, page_size)]

    soup = BeautifulSoup(html, "html.parser")
    urls = [first_url]
    seen = {first_url}
    for link in soup.select('ul.pagination a[href*="startrow="]'):
        url = urljoin(first_url, link.get("href", ""))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _total_results(html: str) -> int | None:
    match = re.search(r"Results\s+\d+\s+[^\d]+\s+\d+\s+of\s+(\d+)", html)
    if not match:
        return None
    return int(match.group(1))


def _page_size(html: str) -> int | None:
    match = re.search(r"Results\s+(\d+)\s+[^\d]+\s+(\d+)\s+of\s+\d+", html)
    if not match:
        return None
    first = int(match.group(1))
    last = int(match.group(2))
    return max(1, last - first + 1)


def _page_url(first_url: str, startrow: int) -> str:
    split_url = urlsplit(first_url)
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(split_url.query, keep_blank_values=True)
        if key != "startrow"
    ]
    if startrow:
        query_pairs.append(("startrow", str(startrow)))
    if "sortColumn" not in {key for key, _value in query_pairs}:
        query_pairs.extend(
            [
                ("sortColumn", "referencedate"),
                ("sortDirection", "desc"),
            ]
        )
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            urlencode(query_pairs),
            "",
        )
    )


def _parse_listing_jobs(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []
    for row in soup.select("tr.data-row"):
        link = row.select_one("a.jobTitle-link[href]")
        if link is None:
            continue
        url = urljoin(base_url, link.get("href", "")).split("#", 1)[0]
        jobs.append(
            {
                "company_name": "DSV",
                "ats_job_id": _job_id_from_url(url),
                "title": _text(link),
                "location": _text(row.select_one("td.colLocation .jobLocation")),
                "department": _text(row.select_one("td.colFacility .jobFacility")),
                "date_posted": _text(row.select_one("td.colDate .jobDate")),
                "url": url,
            }
        )
    return jobs


def _fetch_detail(url: str) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = True
    html = _get_text(session, url)
    soup = BeautifulSoup(html, "html.parser")
    description = soup.select_one('[itemprop="description"] .jobdescription')
    if description is None:
        description = soup.select_one(".jobdescription")
    return {
        "ats_job_id": _job_id_from_url(url),
        "title": _detail_title(soup),
        "description": str(description) if description is not None else "",
        "url": url,
    }


def _detail_title(soup: BeautifulSoup) -> str:
    for selector in ('[itemprop="title"]', "h1", ".jobtitle", ".jobTitle"):
        text = _text(soup.select_one(selector))
        if text:
            return text
    return ""


def _non_empty_values(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value not in (None, "")
    }


def _job_id_from_url(url: str) -> str:
    parts = [part for part in urlsplit(url).path.split("/") if part]
    for part in reversed(parts):
        if part.isdigit():
            return part
    return ""


def _get_text(session: requests.Session, url: str) -> str:
    try:
        response = _request_text(session, url)
    except requests.exceptions.ProxyError as proxy_exc:
        direct_session = requests.Session()
        direct_session.trust_env = False
        try:
            response = _request_text(direct_session, url)
        except requests.RequestException as direct_exc:
            raise FetchError(
                f"Proxy request failed: {proxy_exc}; direct retry also failed: {direct_exc}"
            ) from direct_exc
    except requests.RequestException as exc:
        raise FetchError(str(exc)) from exc
    return response.text


def _request_text(session: requests.Session, url: str) -> requests.Response:
    response = session.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def _text(node: Any) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())
