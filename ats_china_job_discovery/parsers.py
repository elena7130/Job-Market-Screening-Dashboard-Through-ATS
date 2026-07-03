from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


SUPPORTED_ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "jobs.smartrecruiters.com": "smartrecruiters",
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
    return "unsupported"
