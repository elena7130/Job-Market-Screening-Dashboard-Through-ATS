from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
from typing import Any
from urllib.parse import urljoin

import requests

from .common import FetchError, TIMEOUT_SECONDS, USER_AGENT


DETAIL_WORKERS = 6


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    base_url = _board_url(ats_token)
    if "/jobs/" in base_url:
        return [_fetch_job_detail(base_url)]

    listing_html = _get_text(base_url)
    links = _extract_job_links(listing_html, base_url)

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        return list(executor.map(_fetch_job_detail, links))


def _board_url(ats_token: str) -> str:
    host, path_query = _parse_token(ats_token)
    if not path_query.startswith("/"):
        path_query = f"/{path_query}"
    return f"https://{host}{path_query}"


def _parse_token(ats_token: str) -> tuple[str, str]:
    parts = ats_token.split("|", 1)
    if len(parts) != 2 or not all(parts):
        raise FetchError(f"Invalid Teamtailor token: {ats_token}")
    return parts[0], parts[1]


def _extract_job_links(html: str, base_url: str) -> list[str]:
    parser = _JobLinkParser()
    parser.feed(html)
    links = []
    seen: set[str] = set()
    for href in parser.links:
        url = urljoin(base_url, href).split("?")[0].split("#")[0]
        if "/jobs/" not in url or url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def _fetch_job_detail(url: str) -> dict[str, Any]:
    html = _get_text(url)
    parser = _JsonLdParser()
    parser.feed(html)
    job = _job_posting_from_json_ld(parser.scripts) or {}
    job["_teamtailor_url"] = url
    return job


def _job_posting_from_json_ld(scripts: list[str]) -> dict[str, Any] | None:
    for script in scripts:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    return item
    return None


def _get_text(url: str) -> str:
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(str(exc)) from exc
    return response.text


class _JobLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href") or ""
        if "/jobs/" in href:
            self.links.append(href)


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self._in_json_ld = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attrs_dict = dict(attrs)
        if attrs_dict.get("type") == "application/ld+json":
            self._in_json_ld = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json_ld:
            self.scripts.append("".join(self._parts).strip())
            self._in_json_ld = False
            self._parts = []
