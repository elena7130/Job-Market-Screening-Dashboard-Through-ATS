from __future__ import annotations

from pathlib import Path
import sqlite3
from datetime import datetime

import pandas as pd


RECENT_JOB_COLUMNS = [
    "company_name",
    "ats_type",
    "ats_board_token",
    "ats_token",
    "ats_job_id",
    "title",
    "location_raw",
    "location_normalized",
    "is_china",
    "recency_status",
    "fetch_status",
    "ats_published_at",
    "ats_updated_at",
    "first_seen_at",
    "matched_location_keywords",
    "normalized_url",
    "url",
    "jd_text_length",
    "jd_text",
]

COMPANY_COLUMNS = [
    "company_name_guess",
    "ats_type",
    "ats_token",
    "api_status",
    "total_open_jobs",
    "china_keyword_hits",
    "recent_china_keyword_hits",
    "sample_url",
    "last_checked_at",
]


def export_csvs(conn: sqlite3.Connection, exports_dir: Path) -> tuple[int, int]:
    exports_dir.mkdir(parents=True, exist_ok=True)

    jobs_df = pd.read_sql_query(
        """
        SELECT company_name, ats_type, ats_board_token, ats_token, ats_job_id,
               title, location_raw, recency_status, fetch_status, ats_published_at,
               location_normalized, is_china,
               ats_updated_at, first_seen_at, matched_location_keywords,
               normalized_url, url, jd_text_length, jd_text
        FROM jobs
        WHERE is_current = 1
          AND COALESCE(matched_location_keywords, '') <> ''
          AND recency_status IN ('recent_published', 'recent_updated', 'newly_seen')
        ORDER BY company_name, title
        """,
        conn,
    )
    jobs_df = jobs_df.reindex(columns=RECENT_JOB_COLUMNS)
    _write_csv_with_fallback(jobs_df, exports_dir / "recent_china_related_jobs.csv")

    companies_df = pd.read_sql_query(
        """
        SELECT company_name_guess, ats_type, ats_token, api_status,
               total_open_jobs, china_keyword_hits, recent_china_keyword_hits,
               sample_url, last_checked_at
        FROM discovered_companies
        WHERE recent_china_keyword_hits > 0
        ORDER BY company_name_guess, ats_type, ats_token
        """,
        conn,
    )
    companies_df = companies_df.reindex(columns=COMPANY_COLUMNS)
    _write_csv_with_fallback(
        companies_df, exports_dir / "recent_china_related_companies.csv"
    )

    return len(jobs_df), len(companies_df)


def _write_csv_with_fallback(df: pd.DataFrame, path: Path) -> Path:
    try:
        df.to_csv(path, index=False)
        return path
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_path = path.with_name(f"{path.stem}_{timestamp}{path.suffix}")
        df.to_csv(fallback_path, index=False)
        print(f"Could not overwrite locked file: {path}")
        print(f"Wrote fallback export instead: {fallback_path}")
        return fallback_path
