from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import sqlite3
from typing import Any

import requests

import export_recent_china_for_supabase as china_export


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_EXPORT_DIR = BASE_DIR / "output" / "supabase_china_export"
DEFAULT_JOBS_CSV = DEFAULT_EXPORT_DIR / "china_jobs.csv"
DEFAULT_COMPANIES_CSV = DEFAULT_EXPORT_DIR / "china_companies.csv"

BOOL_COLUMNS = {"is_china", "is_europe", "is_remote"}
INTEGER_COLUMNS = {
    "ats_age_days",
    "jd_text_length",
    "total_open_jobs",
    "china_keyword_hits",
    "recent_china_keyword_hits",
}


def main() -> int:
    args = parse_args()

    if args.export_first:
        export_china_csvs(Path(args.export_dir))

    jobs = read_csv_rows(Path(args.jobs_csv))
    companies = read_csv_rows(Path(args.companies_csv))

    if args.dry_run:
        print(f"DRY RUN jobs rows: {len(jobs):,}")
        print(f"DRY RUN companies rows: {len(companies):,}")
        return 0

    supabase_url = _required_env("SUPABASE_URL").rstrip("/")
    supabase_key = _required_env("SUPABASE_SERVICE_ROLE_KEY")

    upload_rows(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        table=args.jobs_table,
        rows=jobs,
        on_conflict="ats_type,ats_token,ats_job_id",
        batch_size=args.batch_size,
    )
    upload_rows(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        table=args.companies_table,
        rows=companies,
        on_conflict="ats_type,ats_token",
        batch_size=args.batch_size,
    )

    print(f"Uploaded jobs: {len(jobs):,} -> {args.jobs_table}")
    print(f"Uploaded companies: {len(companies):,} -> {args.companies_table}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export current China jobs and upsert them into Supabase."
    )
    parser.add_argument(
        "--export-first",
        action="store_true",
        help="Regenerate china_jobs.csv and china_companies.csv before upload.",
    )
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    parser.add_argument("--jobs-csv", default=str(DEFAULT_JOBS_CSV))
    parser.add_argument("--companies-csv", default=str(DEFAULT_COMPANIES_CSV))
    parser.add_argument("--jobs-table", default="china_jobs")
    parser.add_argument("--companies-table", default="china_companies")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def export_china_csvs(export_dir: Path) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(china_export.DEFAULT_DB) as conn:
        jobs_df = china_export.load_china_jobs(conn, recent_only=False)
        companies_df = china_export.load_related_companies(conn, jobs_df)

    jobs_path = export_dir / "china_jobs.csv"
    companies_path = export_dir / "china_companies.csv"
    jobs_df.to_csv(jobs_path, index=False, encoding="utf-8-sig")
    companies_df.to_csv(companies_path, index=False, encoding="utf-8-sig")
    print(f"Exported jobs: {len(jobs_df):,} -> {jobs_path}")
    print(f"Exported companies: {len(companies_df):,} -> {companies_path}")


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [normalize_row(row) for row in reader]


def normalize_row(row: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        text = "" if value is None else str(value)
        if text == "":
            normalized[key] = None
        elif key in BOOL_COLUMNS:
            normalized[key] = text.strip().lower() in {"1", "true", "t", "yes", "y"}
        elif key in INTEGER_COLUMNS:
            normalized[key] = int(float(text))
        else:
            normalized[key] = text
    return normalized


def upload_rows(
    *,
    supabase_url: str,
    supabase_key: str,
    table: str,
    rows: list[dict[str, Any]],
    on_conflict: str,
    batch_size: int,
) -> None:
    if not rows:
        print(f"No rows to upload for {table}.")
        return

    endpoint = f"{supabase_url}/rest/v1/{table}"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    params = {"on_conflict": on_conflict}
    session = requests.Session()
    session.trust_env = False

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        response = session.post(
            endpoint,
            params=params,
            headers=headers,
            json=batch,
            timeout=60,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase upload failed for {table} rows {start + 1}-"
                f"{start + len(batch)}: {response.status_code} {response.text[:1000]}"
            )
        print(f"Uploaded {table}: {min(start + len(batch), len(rows)):,}/{len(rows):,}")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
