from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import import_module
from pathlib import Path
from typing import Any

import requests

from ats_dates import compute_ats_date_info
import db
from fetchers.common import TIMEOUT_SECONDS, USER_AGENT
from keywords import find_location_keywords, is_apac_job, is_europe_job, is_remote_job
from main import classify_fetch_status, now_iso, stable_fallback_job_id
from normalizer import normalize_job
from recency import classify_recency


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "output" / "ats_jobs.db"


def main() -> int:
    args = parse_args()
    conn = db.connect(Path(args.db))

    targets = load_targets(
        conn,
        min_length=args.min_length,
        current_only=args.current_only,
        ats_type=args.ats_type,
        ats_token=args.ats_token,
        limit=args.limit,
    )
    if not targets:
        print("No low-JD jobs found.")
        conn.close()
        return 0

    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
    for row in targets:
        grouped[(row["ats_type"], row["ats_token"])][row["ats_job_id"]] = dict(row)

    print(
        f"Retrying {len(targets)} jobs across {len(grouped)} ATS boards "
        f"(jd_text_length < {args.min_length})"
    )

    stats = {
        "boards": 0,
        "matched": 0,
        "updated": 0,
        "unchanged": 0,
        "errors": 0,
    }
    checked_at = now_iso()

    for (ats_type, ats_token), target_jobs in sorted(grouped.items()):
        stats["boards"] += 1
        print(f"[{stats['boards']}/{len(grouped)}] {ats_type}:{ats_token}", flush=True)
        try:
            if ats_type == "smartrecruiters":
                raw_jobs = fetch_smartrecruiters_details(
                    ats_token, target_jobs, max_workers=args.smartrecruiters_workers
                )
            else:
                fetcher = import_module(f"fetchers.{ats_type}")
                raw_jobs = fetcher.fetch_jobs(ats_token)
        except Exception as exc:
            stats["errors"] += len(target_jobs)
            print(f"  ERROR fetch failed: {exc}", flush=True)
            continue

        for raw in raw_jobs:
            if not isinstance(raw, dict):
                continue
            try:
                job = normalize_job(ats_type, ats_token, raw)
            except Exception as exc:
                stats["errors"] += 1
                print(f"  ERROR normalize failed: {exc}", flush=True)
                continue
            if not job["ats_job_id"]:
                job["ats_job_id"] = stable_fallback_job_id(job)
            existing = target_jobs.get(job["ats_job_id"])
            if not existing:
                continue

            stats["matched"] += 1
            old_length = int(existing["jd_text_length"] or 0)
            jd_text = job.get("description", "")
            new_length = len(jd_text)
            if new_length <= old_length:
                stats["unchanged"] += 1
                continue

            if args.dry_run:
                stats["updated"] += 1
                print(
                    f"  DRY RUN improve #{existing['id']}: {old_length} -> {new_length} "
                    f"{job['title'][:80]}",
                    flush=True,
                )
                continue

            update_job(conn, job, existing, checked_at, jd_text)
            stats["updated"] += 1
            if args.verbose:
                print(
                    f"  updated #{existing['id']}: {old_length} -> {new_length} "
                    f"{job['title'][:80]}",
                    flush=True,
                )

        if not args.dry_run:
            conn.commit()

    if not args.dry_run:
        conn.commit()
    conn.close()

    print("Retry summary")
    for key, value in stats.items():
        print(f"- {key}: {value}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refetch jobs whose jd_text_length is below a threshold."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to ats_jobs.db")
    parser.add_argument("--min-length", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="Max jobs to retry; 0 means all")
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="Only retry jobs currently marked is_current = 1.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--smartrecruiters-workers", type=int, default=8)
    parser.add_argument("--ats-type", default="", help="Only retry this ATS type.")
    parser.add_argument("--ats-token", default="", help="Only retry this ATS token.")
    return parser.parse_args()


def load_targets(
    conn: Any,
    *,
    min_length: int,
    current_only: bool,
    ats_type: str,
    ats_token: str,
    limit: int,
) -> list[Any]:
    where = ["COALESCE(jd_text_length, 0) < ?"]
    params: list[Any] = [min_length]
    if current_only:
        where.append("is_current = 1")
    if ats_type:
        where.append("ats_type = ?")
        params.append(ats_type)
    if ats_token:
        where.append("ats_token = ?")
        params.append(ats_token)
    query = f"""
        SELECT id, company_name, ats_type, ats_token, ats_job_id, first_seen_at,
               jd_text_length
        FROM jobs
        WHERE {" AND ".join(where)}
        ORDER BY ats_type, ats_token, id
    """
    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(query, params).fetchall())


def fetch_smartrecruiters_details(
    ats_token: str, target_jobs: dict[str, Any], *, max_workers: int
) -> list[dict[str, Any]]:
    raw_jobs: list[dict[str, Any]] = []
    job_ids = sorted(target_jobs)
    total = len(job_ids)
    workers = max(1, min(max_workers, total))
    completed = 0
    print(f"  SmartRecruiters detail 0/{total} with {workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_smartrecruiters_detail, ats_token, ats_job_id): ats_job_id
            for ats_job_id in job_ids
        }
        for future in as_completed(futures):
            completed += 1
            if completed % 100 == 0 or completed == total:
                print(f"  SmartRecruiters detail {completed}/{total}", flush=True)
            ats_job_id = futures[future]
            try:
                detail = future.result()
            except Exception as exc:
                print(f"  WARN detail failed {ats_job_id}: {exc}", flush=True)
                continue
            if isinstance(detail, dict):
                raw_jobs.append(detail)
    return raw_jobs


def fetch_smartrecruiters_detail(ats_token: str, ats_job_id: str) -> Any:
    detail_url = (
        f"https://api.smartrecruiters.com/v1/companies/{ats_token}/postings/{ats_job_id}"
    )
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        detail_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def update_job(
    conn: Any, job: dict[str, Any], existing: dict[str, Any], checked_at: str, jd_text: str
) -> None:
    normalized_url = job.get("normalized_url") or job.get("url", "")
    first_seen_at = existing.get("first_seen_at") or checked_at
    matched_keywords = find_location_keywords(
        job["title"], job["location_raw"], jd_text
    )
    recency_status = classify_recency(
        job["ats_published_at"], job["ats_updated_at"], first_seen_at
    )
    ats_date_info = compute_ats_date_info(
        ats_published_at=job["ats_published_at"],
        ats_updated_at=job["ats_updated_at"],
        raw_json=job.get("raw_json"),
    )
    job.update(
        {
            "first_seen_at": first_seen_at,
            "location_normalized": job.get("location_normalized") or job["location_raw"],
            "is_apac": is_apac_job(
                job.get("location_normalized"),
                job["location_raw"],
                job["title"],
                jd_text,
                "; ".join(matched_keywords),
            ),
            "is_europe": is_europe_job(
                job.get("location_normalized"),
                job["location_raw"],
                job["title"],
            ),
            "is_remote": is_remote_job(
                job.get("location_normalized"),
                job["location_raw"],
                job["title"],
            ),
            "last_seen_at": checked_at,
            "fetched_at": checked_at,
            "is_current": 1,
            "jd_text": jd_text,
            "jd_text_length": len(jd_text),
            "normalized_url": normalized_url,
            "fetch_status": classify_fetch_status(normalized_url, jd_text),
            "ats_board_token": job["ats_token"],
            "ats_date_normalized": ats_date_info.normalized,
            "ats_date_source": ats_date_info.source,
            "ats_age_days": ats_date_info.age_days,
            "ats_age_bucket": ats_date_info.bucket,
            "recency_status": recency_status,
            "matched_location_keywords": "; ".join(matched_keywords),
        }
    )
    db.upsert_job(conn, job)


if __name__ == "__main__":
    raise SystemExit(main())
