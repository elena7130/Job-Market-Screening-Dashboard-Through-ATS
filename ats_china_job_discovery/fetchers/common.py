from __future__ import annotations

from typing import Any

import requests


USER_AGENT = (
    "ats-china-job-discovery/0.1 "
    "(public ATS API client; local research MVP)"
)
TIMEOUT_SECONDS = 12


class FetchError(RuntimeError):
    pass


def get_json(url: str, *, params: dict[str, Any] | None = None) -> Any:
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise FetchError(str(exc)) from exc
    except ValueError as exc:
        raise FetchError(f"Invalid JSON response from {url}") from exc
