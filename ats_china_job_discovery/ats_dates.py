from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
from typing import Any


ATS_RAW_DATE_KEYS = [
    "datePosted",
    "postedOn",
    "publishedAt",
    "published_at",
    "releasedDate",
    "releasedAt",
    "createdAt",
    "created_at",
    "startDate",
    "updatedAt",
    "updated_at",
    "updatedDate",
]


@dataclass(frozen=True)
class AtsDateInfo:
    normalized: str
    source: str
    age_days: int | None
    bucket: str


def compute_ats_date_info(
    *,
    ats_published_at: object,
    ats_updated_at: object,
    raw_json: object = None,
    today: date | None = None,
) -> AtsDateInfo:
    today = today or datetime.now().astimezone().date()

    candidates: list[tuple[str, object]] = [
        ("ats_published_at", ats_published_at),
        ("ats_updated_at", ats_updated_at),
    ]
    candidates.extend(_raw_json_date_candidates(raw_json))

    for source, value in candidates:
        parsed = parse_ats_date(value, today=today)
        if parsed is None:
            continue
        age_days = max(0, (today - parsed).days)
        return AtsDateInfo(
            normalized=parsed.isoformat(),
            source=source,
            age_days=age_days,
            bucket=age_bucket(age_days),
        )

    return AtsDateInfo(
        normalized="",
        source="unknown",
        age_days=None,
        bucket="unknown",
    )


def parse_ats_date(value: object, *, today: date | None = None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    today = today or datetime.now().astimezone().date()
    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if "30+" in lowered:
        return today - timedelta(days=31)
    if "today" in lowered:
        return today
    if "yesterday" in lowered:
        return today - timedelta(days=1)

    relative_match = re.search(r"(\d+)\s+days?\s+ago", lowered)
    if relative_match:
        return today - timedelta(days=int(relative_match.group(1)))

    if text.isdigit():
        number = int(text)
        try:
            if number > 10_000_000_000:
                return datetime.fromtimestamp(number / 1000, tz=timezone.utc).date()
            return datetime.fromtimestamp(number, tz=timezone.utc).date()
        except (OSError, OverflowError, ValueError):
            return None

    normalized = (
        text.replace(" UTC", "+00:00")
        .replace(" Z", "+00:00")
        .replace("Z", "+00:00")
    )
    for candidate in (normalized, normalized[:19], normalized[:10]):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            continue

    for date_format in (
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue

    return None


def age_bucket(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= 7:
        return "0-7 days"
    if age_days <= 14:
        return "8-14 days"
    if age_days <= 30:
        return "15-30 days"
    if age_days <= 60:
        return "31-60 days"
    return "60+ days"


def _raw_json_date_candidates(raw_json: object) -> list[tuple[str, object]]:
    if not raw_json:
        return []
    try:
        data = json.loads(str(raw_json))
    except json.JSONDecodeError:
        return []

    candidates: list[tuple[str, object]] = []
    for key, value in _walk_json(data):
        if key in ATS_RAW_DATE_KEYS and value not in (None, ""):
            candidates.append((f"raw_json.{key}", value))
    return candidates


def _walk_json(value: object) -> list[tuple[str, object]]:
    items: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            items.append((str(key), child))
            items.extend(_walk_json(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(_walk_json(child))
    return items
