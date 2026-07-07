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
        company_name=raw.get("company_name"),
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
        company_name=raw.get("company_name"),
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


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _title_from_token(token: str) -> str:
    cleaned = token.replace("-", " ").replace("_", " ")
    return " ".join(word.capitalize() for word in cleaned.split()) or token


def _strip_apply_suffix(url: str) -> str:
    return url[:-6] if url.endswith("/apply") else url
