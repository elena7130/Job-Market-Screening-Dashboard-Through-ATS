from __future__ import annotations

import html
import re

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - dependency fallback for first-run smoke tests.
    BeautifulSoup = None


LOCATION_KEYWORDS = [
    "China",
    "Mainland China",
    "Greater China",
    "Shanghai",
    "Beijing",
    "Shenzhen",
    "Guangzhou",
    "Guangdong",
    "Dongguan",
    "Zhuhai",
    "Hangzhou",
    "Suzhou",
    "Chengdu",
    "Wuhan",
    "Nanjing",
    "Xi'an",
    "APAC",
    "Asia Pacific",
    "Remote Asia",
    "Remote - Asia",
    "Remote APAC",
    "Remote - APAC",
    "China Remote",
    "Remote China",
    "China timezone",
    "Mandarin",
]

APAC_KEYWORDS = [
    "APAC",
    "Asia Pacific",
    "Asia-Pacific",
    "Greater China",
    "Mainland China",
    "China",
    "CN",
    "Hong Kong",
    "HK",
    "Taiwan",
    "Taipei",
    "Singapore",
    "Japan",
    "Korea",
    "South Korea",
    "Australia",
    "New Zealand",
    "India",
    "Thailand",
    "Vietnam",
    "Malaysia",
    "Indonesia",
    "Philippines",
    "Shanghai",
    "Beijing",
    "Shenzhen",
    "Guangzhou",
    "Guangdong",
    "Dongguan",
    "Zhuhai",
    "Hangzhou",
    "Suzhou",
    "Chengdu",
    "Wuhan",
    "Nanjing",
    "Xi'an",
    "Remote Asia",
    "Remote - Asia",
    "Remote APAC",
    "Remote - APAC",
    "Remote, APAC",
    "Remote, China",
]


def html_to_text(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    if "<" not in text or ">" not in text:
        return text
    if BeautifulSoup is None:
        return re.sub(r"<[^>]+>", " ", text)
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)


def find_location_keywords(*values: object) -> list[str]:
    haystack = " ".join(html_to_text(value) for value in values if value is not None)
    haystack = re.sub(r"\s+", " ", haystack).strip().lower()
    matches: list[str] = []
    for keyword in LOCATION_KEYWORDS:
        if keyword.lower() in haystack:
            matches.append(keyword)
    return matches


def is_apac_job(*values: object) -> int:
    haystack = " ".join(html_to_text(value) for value in values if value is not None)
    haystack = re.sub(r"\s+", " ", haystack).strip().lower()
    if not haystack:
        return 0
    return int(any(keyword.lower() in haystack for keyword in APAC_KEYWORDS))
