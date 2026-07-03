from __future__ import annotations

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


def html_to_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
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
