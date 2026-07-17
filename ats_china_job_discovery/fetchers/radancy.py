from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .common import FetchError, TIMEOUT_SECONDS


DETAIL_WORKERS = 6
MAX_PAGES = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    start_url = _url_from_token(ats_token)
    if "/job/" in start_url:
        return [_fetch_job_detail(start_url)]

    session = requests.Session()
    session.trust_env = True
    page_urls = _collect_listing_pages(session, start_url)
    job_urls = _collect_job_urls(session, page_urls)

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        return list(executor.map(_fetch_job_detail, job_urls))


def _url_from_token(ats_token: str) -> str:
    parts = ats_token.split("|", 1)
    if len(parts) != 2 or not all(parts):
        raise FetchError(f"Invalid Radancy token: {ats_token}")
    host, path_query = parts
    if not path_query.startswith("/"):
        path_query = f"/{path_query}"
    return f"https://{host}{path_query}"


def _collect_listing_pages(session: requests.Session, start_url: str) -> list[str]:
    html = _get_text(session, start_url)
    total_pages = min(_total_pages(html), MAX_PAGES)
    return [_page_url(start_url, page) for page in range(1, total_pages + 1)]


def _collect_job_urls(session: requests.Session, page_urls: list[str]) -> list[str]:
    job_urls: list[str] = []
    seen: set[str] = set()
    for page_url in page_urls:
        html = _get_text(session, page_url)
        for job_url in _job_urls_from_listing(html, page_url):
            if job_url in seen:
                continue
            seen.add(job_url)
            job_urls.append(job_url)
    return job_urls


def _job_urls_from_listing(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for link in soup.select('a[href*="/job/"]'):
        url = urljoin(base_url, link.get("href", "")).split("?", 1)[0].split("#", 1)[0]
        if "/job/" in url:
            urls.append(url)
    return urls


def _next_page_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href]"):
        text = _text(link).lower()
        rel = " ".join(link.get("rel") or []).lower()
        aria = str(link.get("aria-label") or "").lower()
        css_class = " ".join(link.get("class") or []).lower()
        marker_text = " ".join([text, rel, aria, css_class])
        if "next" not in marker_text:
            continue
        href = link.get("href", "")
        if href:
            return _normalize_page_url(urljoin(base_url, href))
    return ""


def _total_pages(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    current = soup.select_one(".pagination-current")
    if current is not None:
        try:
            return max(1, int(current.get("max") or 1))
        except ValueError:
            pass

    next_url = _next_page_url(html, "")
    return 2 if next_url else 1


def _page_url(url: str, page: int) -> str:
    split_url = urlsplit(_normalize_page_url(url))
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(split_url.query, keep_blank_values=True)
        if key != "p"
    ]
    if page > 1:
        query_pairs.append(("p", str(page)))
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path.rstrip("/"),
            urlencode(query_pairs),
            "",
        )
    )


def _normalize_page_url(url: str) -> str:
    split_url = urlsplit(url)
    if "&p=" not in split_url.path:
        return url
    path, page = split_url.path.rsplit("&p=", 1)
    query_pairs = parse_qsl(split_url.query, keep_blank_values=True)
    query_pairs = [(key, value) for key, value in query_pairs if key != "p"]
    query_pairs.append(("p", page))
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            path,
            urlencode(query_pairs),
            split_url.fragment,
        )
    )


def _fetch_job_detail(url: str) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = True
    html = _get_text(session, url)
    soup = BeautifulSoup(html, "html.parser")
    fields = _detail_fields(soup)
    apply_link = soup.select_one('a[href*="careers.appliedmaterials.com"], a[href*="/careers/job/"]')
    description_root = _description_root(soup)

    return {
        "company_name": "Applied Materials",
        "ats_job_id": fields.get("Job ID") or _job_id_from_url(url),
        "title": _title(soup),
        "location": fields.get("Location", ""),
        "department": fields.get("Category", ""),
        "description": str(description_root) if description_root is not None else "",
        "url": url,
        "apply_url": urljoin(url, apply_link.get("href", "")) if apply_link else "",
        "date_posted": fields.get("Date posted", ""),
    }


def _detail_fields(soup: BeautifulSoup) -> dict[str, str]:
    labels = {"Job ID", "Date posted", "Location", "Category"}
    strings = [text.strip() for text in soup.stripped_strings if text.strip()]
    fields: dict[str, str] = {}
    for index, text in enumerate(strings[:-1]):
        label = text.rstrip(":")
        if label in labels and strings[index + 1].rstrip(":") not in labels:
            fields[label] = strings[index + 1]
    return fields


def _title(soup: BeautifulSoup) -> str:
    for selector in ("h1", ".job-title", "[data-job-title]"):
        text = _text(soup.select_one(selector))
        if text:
            return text
    title = _text(soup.select_one("title"))
    return title.split(" at ", 1)[0].strip()


def _description_root(soup: BeautifulSoup) -> Any:
    for selector in ("main", ".job-description", ".ats-description", "[data-job-description]"):
        node = soup.select_one(selector)
        if node is not None:
            return node
    return soup.body


def _job_id_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


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
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def _text(node: Any) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())
