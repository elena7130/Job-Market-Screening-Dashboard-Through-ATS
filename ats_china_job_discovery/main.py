from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd

import db
from exporter import export_csvs
from fetchers.common import FetchError
from keywords import find_location_keywords
from normalizer import normalize_job
from parsers import parse_ats_url
from recency import RECENT_STATUSES, classify_recency


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "data" / "search_results.csv"
DEFAULT_OUTPUT = BASE_DIR / "output"
DEFAULT_DB = DEFAULT_OUTPUT / "ats_jobs.db"
DEFAULT_EXPORTS = DEFAULT_OUTPUT / "exports"

REQUIRED_COLUMNS = {"source_query", "result_url"}
OPTIONAL_COLUMNS = {"result_title", "discovered_keyword"}


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    db_path = Path(args.db)
    exports_dir = Path(args.exports)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)

    conn = db.connect(db_path)
    db.init_db(conn)

    search_results = read_search_results(input_path)
    input_url_count = len(search_results)
    if input_url_count == 0:
        print(f"No input URLs found in {input_path}. Add ATS job URLs, then run again.")

    discovered_keys = discover_companies(conn, search_results)

    run_stats = {
        "api_success_companies": 0,
        "jobs_fetched": 0,
        "china_keyword_hit_jobs": 0,
    }

    companies = [
        company
        for company in db.list_discovered_companies(conn)
        if (company["ats_type"], company["ats_token"]) in discovered_keys
    ]

    for company in companies:
        print(f"Fetching {company['ats_type']}:{company['ats_token']} ...", flush=True)
        process_company(conn, company, run_stats)

    recent_jobs_exported, _companies_exported = export_csvs(conn, exports_dir)

    print("Run summary")
    print(f"- input URLs: {input_url_count}")
    print(f"- unique ATS companies discovered: {len(discovered_keys)}")
    print(f"- API-success companies: {run_stats['api_success_companies']}")
    print(f"- jobs fetched: {run_stats['jobs_fetched']}")
    print(f"- China/APAC keyword-hit jobs: {run_stats['china_keyword_hit_jobs']}")
    print(f"- recent China/APAC jobs exported: {recent_jobs_exported}")
    print(f"- database: {db_path}")
    print(f"- exports: {exports_dir}")

    conn.close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover ATS companies from manual search result URLs and fetch public jobs."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Path to search_results.csv")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to ats_jobs.db")
    parser.add_argument("--exports", default=str(DEFAULT_EXPORTS), help="Exports folder")
    return parser.parse_args()


def read_search_results(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    df = pd.read_csv(input_path, dtype=str).fillna("")
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Input CSV missing required columns: {', '.join(sorted(missing))}")

    for column in OPTIONAL_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df


def discover_companies(
    conn: Any, search_results: pd.DataFrame
) -> set[tuple[str, str]]:
    discovered_keys: set[tuple[str, str]] = set()
    now = now_iso()

    for row in search_results.to_dict("records"):
        result_url = row.get("result_url", "")
        if "linkedin.com" in result_url.lower():
            continue

        parsed = parse_ats_url(result_url)
        if not parsed:
            continue

        company = {
            "ats_type": parsed.ats_type,
            "ats_token": parsed.ats_token,
            "company_name_guess": parsed.company_name_guess,
            "sample_url": result_url,
            "discovered_keyword": row.get("discovered_keyword", ""),
            "source_query": row.get("source_query", ""),
            "discovered_at": now,
        }
        db.upsert_discovered_company(conn, company)
        discovered_keys.add((parsed.ats_type, parsed.ats_token))

    return discovered_keys


def process_company(conn: Any, company: Any, run_stats: dict[str, int]) -> None:
    ats_type = company["ats_type"]
    ats_token = company["ats_token"]
    checked_at = now_iso()

    try:
        fetcher = import_module(f"fetchers.{ats_type}")
        raw_jobs = fetcher.fetch_jobs(ats_token)
    except (FetchError, Exception) as exc:
        db.update_company_status(
            conn,
            ats_type,
            ats_token,
            api_status="error",
            api_error=str(exc)[:1000],
            total_open_jobs=0,
            china_keyword_hits=0,
            recent_china_keyword_hits=0,
            last_checked_at=checked_at,
        )
        return

    current_job_ids: set[str] = set()
    china_keyword_hits = 0
    recent_china_keyword_hits = 0

    for raw in raw_jobs:
        if not isinstance(raw, dict):
            continue
        job = normalize_job(ats_type, ats_token, raw)
        if not job["ats_job_id"]:
            job["ats_job_id"] = stable_fallback_job_id(job)

        jd_text = job.get("description", "")
        normalized_url = job.get("normalized_url") or job.get("url", "")
        fetch_status = classify_fetch_status(normalized_url, jd_text)
        first_seen_at = (
            db.get_first_seen_at(conn, ats_type, ats_token, job["ats_job_id"]) or checked_at
        )
        matched_keywords = find_location_keywords(
            job["title"], job["location_raw"], jd_text
        )
        recency_status = classify_recency(
            job["ats_published_at"], job["ats_updated_at"], first_seen_at
        )

        job.update(
            {
                "first_seen_at": first_seen_at,
                "last_seen_at": checked_at,
                "fetched_at": checked_at,
                "is_current": 1,
                "jd_text": jd_text,
                "jd_text_length": len(jd_text),
                "normalized_url": normalized_url,
                "fetch_status": fetch_status,
                "ats_board_token": ats_token,
                "recency_status": recency_status,
                "matched_location_keywords": "; ".join(matched_keywords),
            }
        )
        db.upsert_job(conn, job)
        current_job_ids.add(job["ats_job_id"])

        if matched_keywords:
            china_keyword_hits += 1
            if recency_status in RECENT_STATUSES:
                recent_china_keyword_hits += 1

    db.mark_missing_jobs_not_current(conn, ats_type, ats_token, current_job_ids)
    db.update_company_status(
        conn,
        ats_type,
        ats_token,
        api_status="success",
        api_error=None,
        total_open_jobs=len(current_job_ids),
        china_keyword_hits=china_keyword_hits,
        recent_china_keyword_hits=recent_china_keyword_hits,
        last_checked_at=checked_at,
    )

    run_stats["api_success_companies"] += 1
    run_stats["jobs_fetched"] += len(current_job_ids)
    run_stats["china_keyword_hit_jobs"] += china_keyword_hits


def stable_fallback_job_id(job: dict[str, Any]) -> str:
    basis = "|".join(
        [
            job.get("ats_type", ""),
            job.get("ats_token", ""),
            job.get("url", ""),
            job.get("title", ""),
            job.get("raw_json", ""),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def classify_fetch_status(normalized_url: str, jd_text: str) -> str:
    if not normalized_url:
        return "redirect_failed"
    if not jd_text.strip():
        return "content_empty"
    return "success"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
