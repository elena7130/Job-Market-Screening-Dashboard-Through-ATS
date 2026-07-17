from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from typing import Any
from urllib.parse import parse_qs, urljoin

import requests
from bs4 import BeautifulSoup

from .common import FetchError, TIMEOUT_SECONDS, USER_AGENT


DETAIL_WORKERS = 6


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    host, tenant, page, query = _parse_token(ats_token)
    base_url = f"https://{host}/{tenant}/jobs/{page}"
    if query:
        base_url = f"{base_url}?{query}"

    if page.lower() == "jobdetails.asp":
        return [_fetch_detail(base_url)]

    html = _get_text(base_url)
    links = _job_links_from_search(html, base_url)
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        return list(executor.map(_fetch_detail, links))


def _parse_token(ats_token: str) -> tuple[str, str, str, str]:
    parts = ats_token.split("|", 3)
    if len(parts) < 3 or not all(parts[:3]):
        raise FetchError(f"Invalid SmartSearchOnline token: {ats_token}")
    query = parts[3] if len(parts) == 4 else ""
    return parts[0], parts[1], parts[2], query


def _job_links_from_search(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="jobdetails.asp"]'):
        url = urljoin(base_url, link.get("href", "")).split("#", 1)[0]
        if not _job_id_from_url(url) or url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def _fetch_detail(url: str) -> dict[str, Any]:
    html = _get_text(url)
    soup = BeautifulSoup(html, "html.parser")
    job = _job_posting_from_json_ld(soup) or {}
    job["_smartsearchonline_url"] = url
    job["_smartsearchonline_job_id"] = _job_id_from_url(url)
    return job


def _job_posting_from_json_ld(soup: BeautifulSoup) -> dict[str, Any] | None:
    for script in soup.select('script[type="application/ld+json"]'):
        text = (script.string or script.get_text() or "").strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                data, _end = json.JSONDecoder().raw_decode(text)
            except json.JSONDecodeError:
                continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def _job_id_from_url(url: str) -> str:
    query = url.split("?", 1)[1] if "?" in url else ""
    values = parse_qs(query).get("jo_num") or []
    return values[0].strip() if values else ""


def _get_text(url: str) -> str:
    session = requests.Session()
    session.trust_env = True
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
