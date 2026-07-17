from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode

import requests

from .common import FetchError, TIMEOUT_SECONDS, USER_AGENT


DETAIL_WORKERS = 6
DEFAULT_LIMIT = 100
MAX_PAGES = 20
SEARCH_EXPAND = (
    "requisitionList.workLocation,"
    "requisitionList.otherWorkLocations,"
    "requisitionList.secondaryLocations,"
    "requisitionList.requisitionFlexFields"
)


def fetch_jobs(ats_token: str) -> list[dict[str, Any]]:
    host, site_number, route, route_id, query = _parse_token(ats_token)
    if route in {"job", "requisitions"} and route_id:
        return [_fetch_detail(host, site_number, route_id)]

    session = requests.Session()
    session.trust_env = True
    jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    offset = 0

    for _ in range(MAX_PAGES):
        page = _fetch_search_page(session, host, site_number, query, offset)
        requisitions = page.get("requisitionList") or []
        for requisition in requisitions:
            job_id = str(requisition.get("Id") or "").strip()
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            jobs.append(requisition)

        if not page.get("hasMore") or not requisitions:
            break
        offset += int(page.get("Limit") or DEFAULT_LIMIT)

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        details = list(executor.map(lambda job: _fetch_detail_for_list_item(host, site_number, job), jobs))

    return details


def _parse_token(ats_token: str) -> tuple[str, str, str, str, str]:
    parts = ats_token.split("|", 4)
    if len(parts) < 3 or not all(parts[:3]):
        raise FetchError(f"Invalid Oracle HCM token: {ats_token}")
    host, site_number, route = parts[:3]
    route_id = ""
    query = ""
    if len(parts) >= 4:
        if route in {"job", "requisitions"}:
            route_id = parts[3]
            query = parts[4] if len(parts) == 5 else ""
        else:
            query = parts[3]
    return host, site_number, route, route_id, query


def _fetch_search_page(
    session: requests.Session,
    host: str,
    site_number: str,
    query: str,
    offset: int,
) -> dict[str, Any]:
    search_params = _search_params_from_query(query)
    search_params.update(
        {
            "siteNumber": site_number,
            "facetsList": "jobs",
            "limit": str(DEFAULT_LIMIT),
            "offset": str(offset),
        }
    )
    finder = "findReqs;" + ",".join(
        f"{key}={value}" for key, value in search_params.items() if str(value).strip()
    )
    url = (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        f"?onlyData=true&expand={quote(SEARCH_EXPAND, safe=',')}"
        f"&finder={quote(finder, safe=';,=')}"
    )
    data = _get_json(session, url)
    items = data.get("items") or []
    if not items:
        return {}
    page = items[0]
    page["hasMore"] = bool(page.get("HasMore") or data.get("hasMore"))
    return page


def _search_params_from_query(query: str) -> dict[str, str]:
    allowed = {
        "keyword",
        "location",
        "locationId",
        "radius",
        "radiusUnit",
        "selectedLocationsFacet",
        "selectedWorkLocationsFacet",
        "selectedPostingDatesFacet",
        "selectedTitlesFacet",
        "selectedCategoriesFacet",
        "selectedOrganizationsFacet",
        "selectedFlexFieldsFacets",
        "sortBy",
    }
    params: dict[str, str] = {}
    for key, value in parse_qsl(query, keep_blank_values=False):
        if key in allowed and value:
            params[key] = value
    return params


def _fetch_detail_for_list_item(
    host: str, site_number: str, job: dict[str, Any]
) -> dict[str, Any]:
    job_id = str(job.get("Id") or "").strip()
    detail = _fetch_detail(host, site_number, job_id)
    merged = {**job, **detail}
    merged["_oracle_hcm_site_number"] = site_number
    merged["_oracle_hcm_host"] = host
    return merged


def _fetch_detail(host: str, site_number: str, job_id: str) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = True
    finder = f"ById;Id={job_id}"
    url = (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
        f"?expand=all&onlyData=true&finder={quote(finder, safe=';=')}"
    )
    data = _get_json(session, url)
    items = data.get("items") or []
    if not items:
        raise FetchError(f"Oracle HCM job not found: {job_id}")
    detail = items[0]
    detail["_oracle_hcm_site_number"] = site_number
    detail["_oracle_hcm_host"] = host
    return detail


def _get_json(session: requests.Session, url: str) -> Any:
    try:
        response = _request_json(session, url)
    except requests.exceptions.ProxyError as proxy_exc:
        direct_session = requests.Session()
        direct_session.trust_env = False
        try:
            response = _request_json(direct_session, url)
        except requests.RequestException as direct_exc:
            raise FetchError(
                f"Proxy request failed: {proxy_exc}; direct retry also failed: {direct_exc}"
            ) from direct_exc
    except requests.RequestException as exc:
        raise FetchError(str(exc)) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise FetchError(f"Invalid JSON response from {url}") from exc


def _request_json(session: requests.Session, url: str) -> requests.Response:
    response = session.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response
