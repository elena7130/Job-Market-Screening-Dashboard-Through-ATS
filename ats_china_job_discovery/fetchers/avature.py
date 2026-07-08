from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import parse_qsl, urljoin

import requests
from bs4 import BeautifulSoup

from .common import FetchError, TIMEOUT_SECONDS


DEFAULT_PAGE_SIZE = 6
MAX_PAGES = 20
DETAIL_WORKERS = 6
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    host, locale, portal, page, query = _parse_token(ats_token)
    base_url = f"https://{host}/{locale}/{portal}/{page}/"
    params = _query_params(query)
    page_size = _page_size(params)
    params["jobRecordsPerPage"] = str(page_size)

    session = requests.Session()
    session.trust_env = True
    jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for offset in range(0, page_size * MAX_PAGES, page_size):
        params["jobOffset"] = str(offset)
        html = _get_text(session, base_url, params=params)
        page_jobs = _parse_search_results(html, base_url)
        new_jobs = [job for job in page_jobs if job["url"] not in seen_urls]
        if not new_jobs:
            break

        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
            details = list(executor.map(_fetch_detail_for_job, new_jobs))

        for job, detail in zip(new_jobs, details):
            seen_urls.add(job["url"])
            job.update(detail)
            jobs.append(job)

        if len(page_jobs) < page_size:
            break

    return jobs


def _fetch_detail_for_job(job: dict[str, Any]) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = True
    return _fetch_detail(session, job["url"])


def _parse_token(ats_token: str) -> tuple[str, str, str, str, str]:
    parts = ats_token.split("|", 4)
    if len(parts) != 5 or not all(parts[:4]):
        raise FetchError(f"Invalid Avature token: {ats_token}")
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def _query_params(query: str) -> dict[str, str]:
    return {key: value for key, value in parse_qsl(query, keep_blank_values=True)}


def _page_size(params: dict[str, str]) -> int:
    try:
        return max(1, int(params.get("jobRecordsPerPage") or DEFAULT_PAGE_SIZE))
    except ValueError:
        return DEFAULT_PAGE_SIZE


def _get_text(
    session: requests.Session, url: str, *, params: dict[str, str] | None = None
) -> str:
    try:
        response = _request_text(session, url, params=params)
    except requests.exceptions.ProxyError as proxy_exc:
        direct_session = requests.Session()
        direct_session.trust_env = False
        try:
            response = _request_text(direct_session, url, params=params)
        except requests.RequestException as direct_exc:
            raise FetchError(
                f"Proxy request failed: {proxy_exc}; direct retry also failed: {direct_exc}"
            ) from direct_exc
    except requests.RequestException as exc:
        raise FetchError(str(exc)) from exc
    return response.text


def _request_text(
    session: requests.Session, url: str, *, params: dict[str, str] | None
) -> requests.Response:
    response = session.get(
        url,
        params=params,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def _parse_search_results(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []
    for article in soup.select("article.article--result"):
        link = article.select_one('h3 a[href*="/JobDetail/"]')
        if link is None:
            continue

        url = urljoin(base_url, link.get("href", ""))
        fields = _extract_labeled_fields(article, list_item=True)
        job_id = fields.get("Job Number") or url.rstrip("/").rsplit("/", 1)[-1]
        jobs.append(
            {
                "company_name": _text(article.select_one(".article__header__text__subtitle")),
                "title": _text(link),
                "location": fields.get("Location", ""),
                "ats_job_id": job_id,
                "url": url,
            }
        )
    return jobs


def _fetch_detail(session: requests.Session, url: str) -> dict[str, Any]:
    html = _get_text(session, url)
    soup = BeautifulSoup(html, "html.parser")
    details = soup.select("article.article--details")
    field_values = _extract_labeled_fields(details[0]) if details else {}
    description = ""
    if len(details) > 1:
        description = str(details[1].select_one(".article__content__view") or details[1])

    title = _text(soup.select_one("h2.banner__text__title"))
    return {
        "company_name": field_values.get("Company", ""),
        "title": title,
        "location": field_values.get("Location(s)", ""),
        "department": field_values.get("Career Field", ""),
        "ats_job_id": field_values.get("Job Number", ""),
        "description": description,
    }


def _extract_labeled_fields(root: Any, *, list_item: bool = False) -> dict[str, str]:
    fields: dict[str, str] = {}
    selector = ".article__content__field" if list_item else ".article__content__view__field"
    for field in root.select(selector):
        label_node = field.select_one(
            ".article__content__field__label, .article__content__view__field__label"
        )
        value_node = field.select_one(
            ".article__content__field__value, .article__content__view__field__value"
        )
        label = _text(label_node).rstrip(":")
        value = _text(value_node)
        if label and value:
            fields[label] = value
    return fields


def _text(node: Any) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())
