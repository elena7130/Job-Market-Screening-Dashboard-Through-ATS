from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "output" / "ats_jobs.clean.db"
DEFAULT_EXPORT_DIR = BASE_DIR / "output" / "supabase_recent_china_export"
DEFAULT_ALL_CHINA_EXPORT_DIR = BASE_DIR / "output" / "supabase_china_export"

RECENT_STATUSES = ("recent_published", "recent_updated", "newly_seen")

JOB_COLUMNS = [
    "company_name",
    "ats_type",
    "ats_token",
    "ats_board_token",
    "ats_job_id",
    "title",
    "location_raw",
    "location_normalized",
    "is_china",
    "is_europe",
    "is_remote",
    "recency_status",
    "fetch_status",
    "ats_published_at",
    "ats_updated_at",
    "ats_date_normalized",
    "ats_date_source",
    "ats_age_days",
    "ats_age_bucket",
    "first_seen_at",
    "last_seen_at",
    "fetched_at",
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
    "api_error",
    "total_open_jobs",
    "china_keyword_hits",
    "recent_china_keyword_hits",
    "sample_url",
    "discovered_keyword",
    "source_query",
    "discovered_at",
    "last_checked_at",
]


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    export_dir = Path(args.export_dir)
    if args.all_current_china and export_dir == DEFAULT_EXPORT_DIR:
        export_dir = DEFAULT_ALL_CHINA_EXPORT_DIR

    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    export_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        jobs_df = load_china_jobs(conn, recent_only=not args.all_current_china)
        companies_df = load_related_companies(conn, jobs_df)

    jobs_filename = "china_jobs.csv" if args.all_current_china else "recent_china_jobs.csv"
    companies_filename = (
        "china_companies.csv" if args.all_current_china else "recent_china_companies.csv"
    )
    jobs_path = export_dir / jobs_filename
    companies_path = export_dir / companies_filename
    jobs_df.to_csv(jobs_path, index=False, encoding="utf-8-sig")
    companies_df.to_csv(companies_path, index=False, encoding="utf-8-sig")

    print(f"Exported jobs: {len(jobs_df):,} -> {jobs_path}")
    print(f"Exported companies: {len(companies_df):,} -> {companies_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export current China jobs for Supabase import."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    parser.add_argument(
        "--all-current-china",
        action="store_true",
        help="Export all current jobs where is_china = 1 instead of only recent China jobs.",
    )
    return parser.parse_args()


def load_china_jobs(conn: sqlite3.Connection, *, recent_only: bool) -> pd.DataFrame:
    params: tuple[str, ...] = ()
    recency_filter = ""
    if recent_only:
        placeholders = ",".join("?" for _ in RECENT_STATUSES)
        recency_filter = f"AND recency_status IN ({placeholders})"
        params = RECENT_STATUSES

    query = f"""
        SELECT {", ".join(JOB_COLUMNS)}
        FROM jobs
        WHERE is_current = 1
          AND is_china = 1
          {recency_filter}
        ORDER BY last_seen_at DESC, company_name, title
    """
    return pd.read_sql_query(query, conn, params=params).fillna("")


def load_related_companies(
    conn: sqlite3.Connection, jobs_df: pd.DataFrame
) -> pd.DataFrame:
    if jobs_df.empty:
        return pd.DataFrame(columns=COMPANY_COLUMNS)

    pairs = (
        jobs_df.loc[:, ["ats_type", "ats_token"]]
        .drop_duplicates()
        .sort_values(["ats_type", "ats_token"])
    )
    where_clause = " OR ".join("(ats_type = ? AND ats_token = ?)" for _ in pairs.index)
    params: list[str] = []
    for _, row in pairs.iterrows():
        params.extend([str(row["ats_type"]), str(row["ats_token"])])

    query = f"""
        SELECT {", ".join(COMPANY_COLUMNS)}
        FROM discovered_companies
        WHERE {where_clause}
        ORDER BY company_name_guess, ats_type, ats_token
    """
    return pd.read_sql_query(query, conn, params=params).fillna("")


if __name__ == "__main__":
    raise SystemExit(main())
