from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


SUPPORTED_ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "jobs.smartrecruiters.com": "smartrecruiters",
}

RECRUITEE_CUSTOM_HOSTS = {
    "jobs.dashmote.com": "Dashmote",
}


@dataclass(frozen=True)
class ParsedAtsUrl:
    ats_type: str
    ats_token: str
    company_name_guess: str


def parse_ats_url(url: str) -> ParsedAtsUrl | None:
    parsed = urlparse(str(url).strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    if host == "jobs.thermofisher.com":
        return _parse_thermofisher_url(parsed.path)

    if host == "careers.deetee.com" or host.endswith(".teamtailor.com"):
        return _parse_teamtailor_url(host, parsed.path, parsed.query)

    if host in RECRUITEE_CUSTOM_HOSTS:
        return ParsedAtsUrl(
            ats_type="recruitee",
            ats_token=f"domain:{host}",
            company_name_guess=RECRUITEE_CUSTOM_HOSTS[host],
        )

    if host.endswith(".myworkdayjobs.com"):
        return _parse_workday_url(host, parsed.path, parsed.query)

    if host.endswith(".avature.net"):
        return _parse_avature_url(host, parsed.path, parsed.query)

    if host.endswith(".bamboohr.com"):
        return _parse_subdomain_board_url("bamboohr", host)

    if host.endswith(".breezy.hr"):
        return _parse_subdomain_board_url("breezy", host)

    if host.endswith(".pinpointhq.com"):
        return _parse_subdomain_board_url("pinpoint", host)

    if host == "ats.rippling.com":
        return _parse_rippling_url(parsed.path)

    if host.endswith(".jibeapply.com"):
        return _parse_jibeapply_url(host, parsed.path, parsed.query)

    if host == "comeet.co":
        return _parse_comeet_url(parsed.path, parsed.query)

    ats_type = SUPPORTED_ATS_HOSTS.get(host)
    if not ats_type and host.endswith(".recruitee.com"):
        token = host.removesuffix(".recruitee.com")
        if token and token not in {"www", "careers"}:
            return ParsedAtsUrl(
                ats_type="recruitee",
                ats_token=token,
                company_name_guess=guess_company_name(token),
            )
    if not ats_type:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None

    token = parts[0]
    if not token:
        return None

    return ParsedAtsUrl(
        ats_type=ats_type,
        ats_token=token,
        company_name_guess=guess_company_name(token),
    )


def _parse_workday_url(host: str, path: str, query: str = "") -> ParsedAtsUrl | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return None

    site = parts[1] if "-" in parts[0] else parts[0]
    if not site:
        return None

    tenant = host.split(".", 1)[0].split("-", 1)[0]
    token_parts = [host, tenant, site]
    query_params = parse_qs(query)
    for key in ("locations", "recent_days", "location_keywords"):
        values = [value for value in query_params.get(key, []) if value]
        if values:
            token_parts.append(f"{key}={','.join(values)}")

    token = "|".join(token_parts)
    return ParsedAtsUrl(
        ats_type="workday",
        ats_token=token,
        company_name_guess=guess_company_name(tenant),
    )


def _parse_avature_url(host: str, path: str, query: str = "") -> ParsedAtsUrl | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 3:
        return None

    locale, portal, page = parts[:3]
    if page not in {"SearchJobs", "JobDetail"}:
        return None

    token = "|".join([host, locale, portal, "SearchJobs", query])
    company_token = host.split(".", 1)[0]
    return ParsedAtsUrl(
        ats_type="avature",
        ats_token=token,
        company_name_guess=guess_company_name(company_token),
    )


def _parse_subdomain_board_url(ats_type: str, host: str) -> ParsedAtsUrl | None:
    token = host
    company_token = host.split(".", 1)[0]
    if not company_token or company_token in {"www", "careers", "jobs"}:
        return None
    return ParsedAtsUrl(
        ats_type=ats_type,
        ats_token=token,
        company_name_guess=guess_company_name(company_token),
    )


def _parse_rippling_url(path: str) -> ParsedAtsUrl | None:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    slug = parts[1] if len(parts) > 1 and _looks_locale(parts[0]) else parts[0]
    return ParsedAtsUrl(
        ats_type="rippling",
        ats_token=slug,
        company_name_guess=guess_company_name(slug),
    )


def _looks_locale(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) in {2, 3}


def _parse_jibeapply_url(host: str, path: str, query: str = "") -> ParsedAtsUrl | None:
    if not path or path == "/":
        path = "/jobs"
    if not path.startswith("/api/"):
        path = f"/api{path if path.startswith('/') else '/' + path}"
    token = f"https://{host}{path}"
    if query:
        token = f"{token}?{query}"
    return ParsedAtsUrl(
        ats_type="jibeapply",
        ats_token=token,
        company_name_guess=guess_company_name(host.split(".", 1)[0]),
    )


def _parse_comeet_url(path: str, query: str = "") -> ParsedAtsUrl | None:
    if not path.startswith("/careers-api/"):
        return None
    token = f"https://www.comeet.co{path}"
    if query:
        token = f"{token}?{query}"
    return ParsedAtsUrl(
        ats_type="comeet",
        ats_token=token,
        company_name_guess="Comeet",
    )


def _parse_thermofisher_url(path: str) -> ParsedAtsUrl | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 4 or parts[2] != "c":
        return None

    token = "/".join(parts[:4])
    return ParsedAtsUrl(
        ats_type="thermofisher",
        ats_token=token,
        company_name_guess="Thermo Fisher Scientific",
    )


def _parse_teamtailor_url(host: str, path: str, query: str) -> ParsedAtsUrl | None:
    parts = [part for part in path.split("/") if part]
    if not parts or parts[0] != "jobs":
        return None

    token = f"{host}|{path}"
    if query:
        token = f"{token}?{query}"

    return ParsedAtsUrl(
        ats_type="teamtailor",
        ats_token=token,
        company_name_guess=guess_company_name(_teamtailor_company_token(host)),
    )


def _teamtailor_company_token(host: str) -> str:
    parts = host.split(".")
    if parts[0] == "careers" and len(parts) > 1:
        return parts[1]
    return parts[0]


def guess_company_name(token: str) -> str:
    cleaned = token.replace("-", " ").replace("_", " ").strip()
    return " ".join(word.capitalize() for word in cleaned.split()) or token


def classify_ats_url_kind(url: str) -> str:
    parsed = urlparse(str(url).strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    parts = [part for part in parsed.path.split("/") if part]

    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        return "job_page" if len(parts) >= 3 and parts[1] == "jobs" else "company_page"
    if host == "jobs.lever.co":
        return "job_page" if len(parts) >= 2 else "company_page"
    if host == "jobs.ashbyhq.com":
        return "job_page" if len(parts) >= 2 else "company_page"
    if host == "jobs.smartrecruiters.com":
        return "job_page" if len(parts) >= 2 else "company_page"
    if host.endswith(".recruitee.com"):
        return "job_page" if "o" in parts and len(parts) > parts.index("o") + 1 else "company_page"
    if host in RECRUITEE_CUSTOM_HOSTS:
        return "job_page" if "o" in parts and len(parts) > parts.index("o") + 1 else "company_page"
    if host == "jobs.thermofisher.com":
        return "company_page" if len(parts) >= 4 and parts[2] == "c" else "unsupported"
    if host == "careers.deetee.com" or host.endswith(".teamtailor.com"):
        return "job_page" if len(parts) >= 2 and parts[0] == "jobs" else "company_page"
    if host.endswith(".myworkdayjobs.com"):
        return "job_page" if "job" in parts else "company_page"
    if host.endswith(".avature.net"):
        return "job_page" if "JobDetail" in parts else "company_page"
    if host.endswith(".bamboohr.com"):
        return "job_page" if "careers" in parts and len(parts) >= 2 else "company_page"
    if host.endswith(".breezy.hr"):
        return "job_page" if "p" in parts else "company_page"
    if host.endswith(".pinpointhq.com"):
        return "job_page" if "postings" in parts and len(parts) >= 2 else "company_page"
    if host == "ats.rippling.com":
        if len(parts) >= 3 and parts[1] == "jobs":
            return "job_page"
        if len(parts) >= 4 and _looks_locale(parts[0]) and parts[2] == "jobs":
            return "job_page"
        return "company_page"
    if host.endswith(".jibeapply.com"):
        return "job_page" if "jobs" in parts and len(parts) >= 2 else "company_page"
    if host == "comeet.co":
        return "company_page" if parsed.path.startswith("/careers-api/") else "unsupported"
    return "unsupported"
