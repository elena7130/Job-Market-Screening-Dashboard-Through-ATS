from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


RECENT_STATUSES = {"recent_published", "recent_updated", "newly_seen"}


def today_local() -> date:
    return datetime.now().date()


def cutoff_date(today: date | None = None) -> date:
    return (today or today_local()) - timedelta(days=30)


def classify_recency(
    published_at: str | None,
    updated_at: str | None,
    first_seen_at: str | None,
    *,
    today: date | None = None,
) -> str:
    cutoff = cutoff_date(today)
    published_date = parse_date(published_at)
    updated_date = parse_date(updated_at)
    first_seen_date = parse_date(first_seen_at)

    if published_date and published_date >= cutoff:
        return "recent_published"
    if updated_date and updated_date >= cutoff:
        return "recent_updated"
    if first_seen_date and first_seen_date >= cutoff:
        return "newly_seen"
    return "current_but_old_or_unknown"


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit():
        number = int(text)
        try:
            if number > 10_000_000_000:
                return datetime.fromtimestamp(number / 1000, tz=timezone.utc).date()
            return datetime.fromtimestamp(number, tz=timezone.utc).date()
        except (OSError, OverflowError, ValueError):
            return None

    normalized = text.replace("Z", "+00:00")
    for candidate in (normalized, normalized[:19], normalized[:10]):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            continue
    return None
