from __future__ import annotations

import json
from typing import Any

from keywords import html_to_text


def normalize_job(ats_type: str, ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    if ats_type == "greenhouse":
        return _normalize_greenhouse(ats_token, raw)
    if ats_type == "lever":
        return _normalize_lever(ats_token, raw)
    if ats_type == "ashby":
        return _normalize_ashby(ats_token, raw)
    if ats_type == "smartrecruiters":
        return _normalize_smartrecruiters(ats_token, raw)
    if ats_type == "recruitee":
        return _normalize_recruitee(ats_token, raw)
    if ats_type == "workday":
        return _normalize_workday(ats_token, raw)
    if ats_type == "thermofisher":
        return _normalize_thermofisher(ats_token, raw)
    if ats_type == "teamtailor":
        return _normalize_teamtailor(ats_token, raw)
    if ats_type == "avature":
        return _normalize_avature(ats_token, raw)
    if ats_type == "bamboohr":
        return _normalize_bamboohr(ats_token, raw)
    if ats_type == "breezy":
        return _normalize_breezy(ats_token, raw)
    if ats_type == "pinpoint":
        return _normalize_pinpoint(ats_token, raw)
    if ats_type == "rippling":
        return _normalize_rippling(ats_token, raw)
    if ats_type == "jibeapply":
        return _normalize_jibeapply(ats_token, raw)
    if ats_type == "comeet":
        return _normalize_comeet(ats_token, raw)
    raise ValueError(f"Unsupported ATS type: {ats_type}")


def _base(
    *,
    company_name: str | None,
    ats_type: str,
    ats_token: str,
    ats_job_id: object,
    title: object,
    location_raw: object,
    description: object,
    department: object,
    url: object,
    ats_published_at: object = None,
    ats_updated_at: object = None,
    raw: dict[str, Any],
) -> dict[str, Any]:
    return {
        "company_name": _clean_text(company_name) or _title_from_token(ats_token),
        "ats_type": ats_type,
        "ats_token": ats_token,
        "ats_board_token": ats_token,
        "ats_job_id": str(ats_job_id or "").strip(),
        "title": _clean_text(title),
        "location_raw": _clean_text(location_raw),
        "description": html_to_text(description),
        "department": _clean_text(department),
        "url": _clean_text(url),
        "ats_published_at": _clean_text(ats_published_at),
        "ats_updated_at": _clean_text(ats_updated_at),
        "raw_json": json.dumps(raw, ensure_ascii=False, sort_keys=True),
    }


def _normalize_greenhouse(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    departments = raw.get("departments") or []
    department = ", ".join(
        item.get("name", "") for item in departments if isinstance(item, dict)
    )
    location = raw.get("location")
    location_name = location.get("name") if isinstance(location, dict) else location
    job = _base(
        company_name=raw.get("company_name") or _company_from_token(ats_token),
        ats_type="greenhouse",
        ats_token=ats_token,
        ats_job_id=raw.get("id"),
        title=raw.get("title"),
        location_raw=location_name,
        description=raw.get("content"),
        department=department,
        url=raw.get("absolute_url"),
        ats_updated_at=raw.get("updated_at"),
        raw=raw,
    )
    if job["ats_job_id"]:
        job["normalized_url"] = (
            f"https://job-boards.greenhouse.io/{ats_token}/jobs/{job['ats_job_id']}"
        )
    return job


def _normalize_lever(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    categories = raw.get("categories") or {}
    location = categories.get("location") if isinstance(categories, dict) else None
    department = None
    if isinstance(categories, dict):
        department = categories.get("department") or categories.get("team")

    content = raw.get("content") or {}
    description = raw.get("description") or raw.get("descriptionPlain")
    if isinstance(content, dict):
        parts = [content.get("description"), content.get("closing")]
        lists = content.get("lists") or []
        for item in lists:
            if not isinstance(item, dict):
                continue
            parts.extend([item.get("text"), item.get("content")])
        parts.append(raw.get("additional"))
        description = "\n".join(str(part) for part in parts if part)
    elif raw.get("additional"):
        description = "\n".join(
            str(part)
            for part in [description, raw.get("additional")]
            if part
        )

    job = _base(
        company_name=raw.get("company"),
        ats_type="lever",
        ats_token=ats_token,
        ats_job_id=raw.get("id"),
        title=raw.get("text"),
        location_raw=location,
        description=description,
        department=department,
        url=raw.get("hostedUrl") or raw.get("applyUrl"),
        ats_published_at=raw.get("createdAt"),
        ats_updated_at=raw.get("updatedAt"),
        raw=raw,
    )
    job["normalized_url"] = _strip_apply_suffix(job["url"])
    return job


def _normalize_ashby(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    location = raw.get("location")
    if isinstance(location, dict):
        location = location.get("name") or location.get("text")

    remote_bits = []
    for key in ("workplaceType", "isRemote"):
        if key in raw:
            remote_bits.append(f"{key}: {raw.get(key)}")
    location_raw = " | ".join(part for part in [location, *remote_bits] if part)

    department = raw.get("department")
    if isinstance(department, dict):
        department = department.get("name")

    job = _base(
        company_name=raw.get("companyName"),
        ats_type="ashby",
        ats_token=ats_token,
        ats_job_id=raw.get("id") or raw.get("jobId"),
        title=raw.get("title"),
        location_raw=location_raw,
        description=raw.get("descriptionPlain") or raw.get("descriptionHtml"),
        department=department or raw.get("team"),
        url=raw.get("jobUrl") or raw.get("url"),
        ats_published_at=raw.get("publishedAt"),
        ats_updated_at=raw.get("updatedAt"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _normalize_smartrecruiters(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    location = raw.get("location")
    if isinstance(location, dict):
        location = ", ".join(
            str(location.get(key))
            for key in ("city", "region", "country")
            if location.get(key)
        ) or location.get("fullLocation")

    department = raw.get("department")
    if isinstance(department, dict):
        department = department.get("label") or department.get("name")

    job = _base(
        company_name=raw.get("company", {}).get("name")
        if isinstance(raw.get("company"), dict)
        else None,
        ats_type="smartrecruiters",
        ats_token=ats_token,
        ats_job_id=raw.get("id") or raw.get("uuid"),
        title=raw.get("name") or raw.get("title"),
        location_raw=location,
        description=raw.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get(
            "text"
        )
        if isinstance(raw.get("jobAd"), dict)
        else raw.get("description"),
        department=department,
        url=raw.get("postingUrl") or raw.get("ref"),
        ats_published_at=raw.get("releasedDate") or raw.get("releasedAt"),
        ats_updated_at=raw.get("updatedDate") or raw.get("updatedAt"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _normalize_recruitee(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    location = raw.get("location")
    if isinstance(location, dict):
        location = ", ".join(
            str(location.get(key))
            for key in ("city", "state", "country", "name")
            if location.get(key)
        )

    department = raw.get("department")
    if isinstance(department, dict):
        department = department.get("name")

    description = (
        raw.get("description")
        or raw.get("description_html")
        or raw.get("requirements")
        or raw.get("body")
    )
    if isinstance(description, list):
        description = "\n".join(str(part) for part in description if part)

    url = (
        raw.get("careers_url")
        or raw.get("url")
        or raw.get("sharing_url")
        or raw.get("apply_url")
    )
    slug = raw.get("slug") or raw.get("offer_slug")
    if not url and slug:
        url = f"https://{_recruitee_host(ats_token)}/o/{slug}"

    job = _base(
        company_name=raw.get("company_name") or _company_from_token(ats_token),
        ats_type="recruitee",
        ats_token=ats_token,
        ats_job_id=raw.get("id") or raw.get("offer_id") or slug,
        title=raw.get("title") or raw.get("name"),
        location_raw=location or raw.get("location_name"),
        description=description,
        department=department,
        url=url,
        ats_published_at=raw.get("published_at") or raw.get("created_at"),
        ats_updated_at=raw.get("updated_at"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _recruitee_host(ats_token: str) -> str:
    if ats_token.startswith("domain:"):
        return ats_token.removeprefix("domain:")
    return f"{ats_token}.recruitee.com"


def _normalize_workday(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    return _normalize_workday_like(
        ats_type="workday",
        ats_token=ats_token,
        raw=raw,
        company_name=raw.get("company_name"),
    )


def _normalize_thermofisher(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    return _normalize_workday_like(
        ats_type="thermofisher",
        ats_token=ats_token,
        raw=raw,
        company_name="Thermo Fisher Scientific",
    )


def _normalize_workday_like(
    *,
    ats_type: str,
    ats_token: str,
    raw: dict[str, Any],
    company_name: object,
) -> dict[str, Any]:
    detail = raw.get("_workday_detail")
    if not isinstance(detail, dict):
        detail = {}

    posting_info = detail.get("jobPostingInfo")
    if not isinstance(posting_info, dict):
        posting_info = {}

    hiring_org = detail.get("hiringOrganization")
    if not isinstance(hiring_org, dict):
        hiring_org = {}

    location = (
        raw.get("locationsText")
        or posting_info.get("location")
        or posting_info.get("primaryLocation")
        or posting_info.get("additionalLocationsText")
    )
    if isinstance(location, dict):
        location = location.get("descriptor") or location.get("name")
    if isinstance(location, list):
        location = ", ".join(str(item) for item in location if item)

    external_path = raw.get("externalPath") or posting_info.get("externalPath")
    url = posting_info.get("externalUrl") or raw.get("url")
    host = raw.get("_workday_host")
    site = raw.get("_workday_site")
    if not url and host and site and external_path:
        path = str(external_path)
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"https://{host}/en-US/{site}{path}"

    description = (
        posting_info.get("jobDescription")
        or raw.get("jobDescription")
        or raw.get("description")
    )

    job = _base(
        company_name=company_name or hiring_org.get("name") or raw.get("company_name"),
        ats_type=ats_type,
        ats_token=ats_token,
        ats_job_id=posting_info.get("id") or _workday_requisition_id(raw) or external_path,
        title=posting_info.get("title") or raw.get("title"),
        location_raw=location,
        description=description,
        department=posting_info.get("jobFamily") or raw.get("department"),
        url=url,
        ats_published_at=raw.get("postedOn") or posting_info.get("postedOn"),
        ats_updated_at=posting_info.get("updatedDate") or posting_info.get("startDate"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _workday_requisition_id(raw: dict[str, Any]) -> str:
    fields = raw.get("bulletFields")
    if isinstance(fields, list):
        return " ".join(str(field) for field in fields if field).strip()
    return ""


def _normalize_teamtailor(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    identifier = raw.get("identifier")
    if not isinstance(identifier, dict):
        identifier = {}

    hiring_org = raw.get("hiringOrganization")
    if not isinstance(hiring_org, dict):
        hiring_org = {}

    job = _base(
        company_name=hiring_org.get("name"),
        ats_type="teamtailor",
        ats_token=ats_token,
        ats_job_id=identifier.get("value") or _teamtailor_id_from_url(raw),
        title=raw.get("title"),
        location_raw=_teamtailor_location(raw.get("jobLocation")),
        description=raw.get("description"),
        department=raw.get("employmentType"),
        url=raw.get("_teamtailor_url") or raw.get("url"),
        ats_published_at=raw.get("datePosted"),
        ats_updated_at=raw.get("validThrough"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _teamtailor_location(value: object) -> str:
    locations = value if isinstance(value, list) else [value]
    parts = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if not isinstance(address, dict):
            continue
        address_parts = [
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        ]
        text = ", ".join(str(part) for part in address_parts if part)
        if text:
            parts.append(text)
    return " | ".join(parts)


def _teamtailor_id_from_url(raw: dict[str, Any]) -> str:
    url = str(raw.get("_teamtailor_url") or raw.get("url") or "")
    marker = "/jobs/"
    if marker not in url:
        return ""
    return url.split(marker, 1)[1].split("-", 1)[0].strip("/")


def _normalize_avature(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    job = _base(
        company_name=raw.get("company_name") or _company_from_token(ats_token),
        ats_type="avature",
        ats_token=ats_token,
        ats_job_id=raw.get("ats_job_id"),
        title=raw.get("title"),
        location_raw=raw.get("location"),
        description=raw.get("description"),
        department=raw.get("department"),
        url=raw.get("url"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _normalize_bamboohr(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    detail = _dict_value(raw.get("_bamboohr_detail"))
    result = _dict_value(detail.get("result")) or detail
    location = _dict_value(raw.get("location"))
    remote = "Remote" if raw.get("isRemote") else ""
    location_raw = _join_parts([location.get("city"), location.get("state"), remote])
    job_id = raw.get("id") or result.get("id")
    origin = raw.get("_bamboohr_origin") or f"https://{ats_token}"
    url = raw.get("jobOpeningShareUrl") or result.get("jobOpeningShareUrl")
    if not url and job_id:
        url = f"{origin}/careers/{job_id}"
    job = _base(
        company_name=raw.get("company_name") or _company_from_token(ats_token),
        ats_type="bamboohr",
        ats_token=ats_token,
        ats_job_id=job_id,
        title=result.get("jobOpeningName") or raw.get("jobOpeningName"),
        location_raw=location_raw,
        description=result.get("description") or result.get("jobDescription"),
        department=raw.get("employmentStatusLabel") or result.get("employmentStatusLabel"),
        url=url,
        ats_published_at=result.get("datePosted") or raw.get("datePosted"),
        ats_updated_at=result.get("lastUpdated") or raw.get("lastUpdated"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _normalize_breezy(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    location = _dict_value(raw.get("location"))
    country = _dict_value(location.get("country"))
    location_raw = location.get("name") or _join_parts(
        [
            location.get("city"),
            location.get("state"),
            country.get("name"),
            "Remote" if location.get("is_remote") else "",
        ]
    )
    description = raw.get("description") or raw.get("summary")
    if isinstance(description, dict):
        description = "\n".join(str(value) for value in description.values() if value)
    job = _base(
        company_name=raw.get("company_name"),
        ats_type="breezy",
        ats_token=ats_token,
        ats_job_id=raw.get("_id") or raw.get("id") or _id_from_url(raw.get("url")),
        title=raw.get("name") or raw.get("title"),
        location_raw=location_raw,
        description=description,
        department=raw.get("department"),
        url=raw.get("url"),
        ats_published_at=raw.get("published_date") or raw.get("created_at"),
        ats_updated_at=raw.get("updated_date") or raw.get("updated_at"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _normalize_pinpoint(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    location = _dict_value(raw.get("location"))
    job_info = _dict_value(raw.get("job"))
    job = _base(
        company_name=raw.get("company_name"),
        ats_type="pinpoint",
        ats_token=ats_token,
        ats_job_id=raw.get("id") or _id_from_url(raw.get("url") or raw.get("path")),
        title=raw.get("title"),
        location_raw=location.get("name") or _join_parts(
            [location.get("city"), location.get("province"), location.get("country")]
        ),
        description=raw.get("description") or raw.get("content"),
        department=job_info.get("department") or job_info.get("division"),
        url=raw.get("url"),
        ats_published_at=raw.get("published_at") or raw.get("created_at"),
        ats_updated_at=raw.get("updated_at"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _normalize_rippling(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    location = raw.get("workLocation")
    if isinstance(location, dict):
        location = location.get("label") or location.get("name")
    department = raw.get("department")
    if isinstance(department, dict):
        department = department.get("label") or department.get("name")
    job = _base(
        company_name=raw.get("company_name"),
        ats_type="rippling",
        ats_token=ats_token,
        ats_job_id=raw.get("uuid") or raw.get("id") or _id_from_url(raw.get("url")),
        title=raw.get("name") or raw.get("title"),
        location_raw=location,
        description=raw.get("description") or raw.get("jobDescription"),
        department=department,
        url=raw.get("url"),
        ats_published_at=raw.get("publishedAt") or raw.get("createdAt"),
        ats_updated_at=raw.get("updatedAt"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _normalize_jibeapply(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    data = _dict_value(raw.get("data")) or raw
    slug = data.get("slug") or data.get("req_id") or data.get("id")
    origin = _origin_from_url(ats_token)
    url = data.get("url") or data.get("apply_url")
    if not url and slug and origin:
        url = f"{origin}/jobs/{slug}"
    job = _base(
        company_name=data.get("hiring_organization") or data.get("company") or _company_from_token(ats_token),
        ats_type="jibeapply",
        ats_token=ats_token,
        ats_job_id=data.get("req_id") or data.get("id") or slug,
        title=data.get("title"),
        location_raw=data.get("full_location") or _join_parts([data.get("city"), data.get("country")]),
        description=data.get("description") or data.get("job_description") or data.get("summary"),
        department=data.get("category") or data.get("department"),
        url=url,
        ats_published_at=data.get("posted_date") or data.get("date_posted"),
        ats_updated_at=data.get("updated_at"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _normalize_comeet(ats_token: str, raw: dict[str, Any]) -> dict[str, Any]:
    location = _dict_value(raw.get("location"))
    remote = "Remote" if location.get("is_remote") else ""
    description = _join_parts(
        [
            raw.get("description"),
            raw.get("requirements"),
            raw.get("responsibilities"),
        ],
        separator="\n",
    )
    job = _base(
        company_name=raw.get("company_name") or _company_from_token(ats_token),
        ats_type="comeet",
        ats_token=ats_token,
        ats_job_id=raw.get("uid") or raw.get("id") or _id_from_url(raw.get("url_active_page")),
        title=raw.get("name") or raw.get("title"),
        location_raw=_join_parts([location.get("name"), remote]),
        description=description,
        department=raw.get("department") or raw.get("position_department"),
        url=raw.get("url_active_page") or raw.get("url_comeet_hosted_page"),
        ats_published_at=raw.get("time_created"),
        ats_updated_at=raw.get("time_updated"),
        raw=raw,
    )
    job["normalized_url"] = job["url"]
    return job


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _title_from_token(token: str) -> str:
    cleaned = token.replace("-", " ").replace("_", " ")
    return " ".join(word.capitalize() for word in cleaned.split()) or token


def _company_from_token(token: str) -> str:
    value = token
    if token.startswith("https://"):
        value = token.removeprefix("https://").split("/", 1)[0]
    if "." in value:
        value = value.split(".", 1)[0]
    return _title_from_token(value)


def _strip_apply_suffix(url: str) -> str:
    return url[:-6] if url.endswith("/apply") else url


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _join_parts(parts: list[object], *, separator: str = ", ") -> str:
    return separator.join(str(part).strip() for part in parts if str(part or "").strip())


def _id_from_url(url: object) -> str:
    text = str(url or "").strip().rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _origin_from_url(url: object) -> str:
    text = str(url or "").strip()
    if not text.startswith("http"):
        return ""
    parts = text.split("/", 3)
    return "/".join(parts[:3]) if len(parts) >= 3 else ""
