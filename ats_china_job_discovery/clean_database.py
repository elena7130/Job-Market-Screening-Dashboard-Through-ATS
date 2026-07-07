from __future__ import annotations

import argparse
import csv
import html
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import db as app_db
from ats_dates import compute_ats_date_info
from keywords import html_to_text, is_apac_job


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DB = BASE_DIR / "output" / "ats_jobs.db"
DEFAULT_CLEAN_DB = BASE_DIR / "output" / "ats_jobs.clean.db"
DEFAULT_EXPORT_DIR = BASE_DIR / "output" / "supabase_clean_export"

TEXT_COLUMNS = [
    "company_name",
    "title",
    "location_raw",
    "location_normalized",
    "department",
    "url",
    "normalized_url",
    "fetch_status",
    "ats_board_token",
    "ats_date_normalized",
    "ats_date_source",
    "ats_age_bucket",
    "recency_status",
    "matched_location_keywords",
]

EXPORT_TABLES = ["discovered_companies", "discovery_candidates", "jobs"]
MOJIBAKE_MARKERS = ["\ufffd", "Ã", "Â", "â€™", "â€œ", "â€", "�"]
EMPTY_JD_VALUES = {"", "-", ".", "n/a", "na", "none", "null", "<p>-</p>"}


def main() -> int:
    args = parse_args()
    source_db = Path(args.source_db)
    clean_db = Path(args.clean_db)
    export_dir = Path(args.export_dir)

    if not source_db.exists():
        raise FileNotFoundError(f"Source DB not found: {source_db}")

    sync_stats, stats = run_cleaning(
        source_db=source_db,
        clean_db=clean_db,
        rebuild=args.rebuild_clean_db,
        export_csvs_enabled=args.export_csvs,
        export_dir=export_dir,
        max_jd_length=args.max_jd_length,
        keep_raw_json=args.keep_raw_json,
    )

    print(f"Source DB: {source_db}")
    print(f"Clean DB: {clean_db}")
    if args.export_csvs:
        print(f"Clean CSV export: {export_dir}")
    else:
        print("Clean CSV export: skipped; use --export-csvs when needed")
    print("Clean sync summary")
    for key, value in sync_stats.items():
        print(f"- {key}: {value}")
    print("Clean summary")
    for key, value in stats.items():
        print(f"- {key}: {value}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update a cleaned copy of the ATS jobs database."
    )
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB))
    parser.add_argument("--clean-db", default=str(DEFAULT_CLEAN_DB))
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    parser.add_argument("--max-jd-length", type=int, default=50000)
    parser.add_argument(
        "--export-csvs",
        action="store_true",
        help="Export cleaned CSV files after updating the clean database.",
    )
    parser.add_argument(
        "--rebuild-clean-db",
        action="store_true",
        help="Overwrite the clean database from the source database before cleaning.",
    )
    parser.add_argument(
        "--keep-raw-json",
        action="store_true",
        help="Keep raw_json in the clean database and CSV export.",
    )
    return parser.parse_args()


def run_cleaning(
    *,
    source_db: Path,
    clean_db: Path,
    rebuild: bool = False,
    export_csvs_enabled: bool = False,
    export_dir: Path = DEFAULT_EXPORT_DIR,
    max_jd_length: int = 50000,
    keep_raw_json: bool = False,
) -> tuple[dict[str, int], dict[str, int]]:
    clean_db.parent.mkdir(parents=True, exist_ok=True)
    sync_stats = prepare_clean_db(
        source_db=source_db,
        clean_db=clean_db,
        rebuild=rebuild,
    )

    conn = sqlite3.connect(clean_db)
    conn.row_factory = sqlite3.Row
    app_db.init_db(conn)
    ensure_jobs_columns(conn)
    stats = clean_jobs(
        conn,
        max_jd_length=max_jd_length,
        keep_raw_json=keep_raw_json,
    )
    conn.commit()

    if export_csvs_enabled:
        export_dir.mkdir(parents=True, exist_ok=True)
        export_csvs(conn, export_dir)
    conn.close()
    return sync_stats, stats


def prepare_clean_db(
    *, source_db: Path, clean_db: Path, rebuild: bool
) -> dict[str, int]:
    if rebuild or not clean_db.exists():
        shutil.copy2(source_db, clean_db)
        return {
            "clean_db_rebuilt": 1,
            "jobs_inserted": 0,
            "jobs_updated": 0,
            "companies_inserted": 0,
            "companies_updated": 0,
            "candidates_inserted": 0,
            "candidates_updated": 0,
        }

    source_conn = sqlite3.connect(source_db)
    source_conn.row_factory = sqlite3.Row
    clean_conn = sqlite3.connect(clean_db)
    clean_conn.row_factory = sqlite3.Row
    app_db.init_db(clean_conn)

    for table in EXPORT_TABLES:
        ensure_table_columns_from_source(source_conn, clean_conn, table)

    stats = {
        "clean_db_rebuilt": 0,
        "jobs_inserted": 0,
        "jobs_updated": 0,
        "companies_inserted": 0,
        "companies_updated": 0,
        "candidates_inserted": 0,
        "candidates_updated": 0,
    }
    inserted, updated = sync_table(
        source_conn,
        clean_conn,
        table="discovered_companies",
        key_columns=["ats_type", "ats_token"],
    )
    stats["companies_inserted"] = inserted
    stats["companies_updated"] = updated

    inserted, updated = sync_table(
        source_conn,
        clean_conn,
        table="discovery_candidates",
        key_columns=["result_url"],
        preserve_existing_columns=["status", "reviewed_at", "notes"],
    )
    stats["candidates_inserted"] = inserted
    stats["candidates_updated"] = updated

    inserted, updated = sync_table(
        source_conn,
        clean_conn,
        table="jobs",
        key_columns=["ats_type", "ats_token", "ats_job_id"],
        preserve_existing_columns=["location_normalized"],
    )
    stats["jobs_inserted"] = inserted
    stats["jobs_updated"] = updated

    clean_conn.commit()
    source_conn.close()
    clean_conn.close()
    return stats


def ensure_table_columns_from_source(
    source_conn: sqlite3.Connection, clean_conn: sqlite3.Connection, table: str
) -> None:
    source_columns = {
        row["name"]: row["type"] or "TEXT"
        for row in source_conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    clean_columns = {
        row["name"]
        for row in clean_conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for column, column_type in source_columns.items():
        if column not in clean_columns:
            clean_conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def sync_table(
    source_conn: sqlite3.Connection,
    clean_conn: sqlite3.Connection,
    *,
    table: str,
    key_columns: list[str],
    preserve_existing_columns: list[str] | None = None,
) -> tuple[int, int]:
    preserve_existing_columns = preserve_existing_columns or []
    source_columns = [
        row["name"]
        for row in source_conn.execute(f"PRAGMA table_info({table})").fetchall()
        if row["name"] != "id"
    ]
    clean_columns = {
        row["name"]
        for row in clean_conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    columns = [column for column in source_columns if column in clean_columns]

    inserted = 0
    updated = 0
    for source_row in source_conn.execute(f"SELECT * FROM {table}").fetchall():
        where_clause = " AND ".join(f"{column} = ?" for column in key_columns)
        key_values = [source_row[column] for column in key_columns]
        existing_row = clean_conn.execute(
            f"SELECT * FROM {table} WHERE {where_clause}",
            key_values,
        ).fetchone()

        values = {column: source_row[column] for column in columns}
        if existing_row is None:
            insert_columns = list(values)
            placeholders = ", ".join("?" for _ in insert_columns)
            clean_conn.execute(
                f"""
                INSERT INTO {table} ({", ".join(insert_columns)})
                VALUES ({placeholders})
                """,
                [values[column] for column in insert_columns],
            )
            inserted += 1
            continue

        for column in preserve_existing_columns:
            if column in values and column in existing_row.keys():
                existing_value = existing_row[column]
                if existing_value not in (None, ""):
                    values[column] = existing_value

        update_columns = [column for column in columns if column not in key_columns]
        set_clause = ", ".join(f"{column} = ?" for column in update_columns)
        clean_conn.execute(
            f"UPDATE {table} SET {set_clause} WHERE {where_clause}",
            [values[column] for column in update_columns] + key_values,
        )
        updated += 1

    return inserted, updated


def ensure_jobs_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "location_normalized" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN location_normalized TEXT")
    if "is_apac" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN is_apac INTEGER")
    if "ats_date_normalized" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN ats_date_normalized TEXT")
    if "ats_date_source" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN ats_date_source TEXT")
    if "ats_age_days" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN ats_age_days INTEGER")
    if "ats_age_bucket" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN ats_age_bucket TEXT")
    conn.execute(
        """
        UPDATE jobs
        SET location_normalized = CASE
            WHEN location_raw IS NULL THEN ''
            ELSE location_raw
        END
        WHERE location_normalized IS NULL OR location_normalized = ''
        """
    )


def clean_jobs(
    conn: sqlite3.Connection, *, max_jd_length: int, keep_raw_json: bool
) -> dict[str, int]:
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    stats = {
        "jobs_seen": len(rows),
        "text_fields_changed": 0,
        "jd_cleaned": 0,
        "jd_cleared_mojibake": 0,
        "jd_cleared_empty": 0,
        "jd_truncated": 0,
        "raw_json_cleared": 0,
        "is_apac_marked": 0,
    }

    for row in rows:
        updates: dict[str, Any] = {}
        for column in TEXT_COLUMNS:
            cleaned = clean_small_text(row[column])
            if cleaned != (row[column] or ""):
                updates[column] = cleaned
                stats["text_fields_changed"] += 1

        old_jd = row["jd_text"] or row["description"] or ""
        jd_text = clean_jd_text(old_jd)
        if is_empty_jd(jd_text):
            jd_text = ""
            if old_jd:
                stats["jd_cleared_empty"] += 1
        elif is_mojibake(jd_text):
            jd_text = ""
            stats["jd_cleared_mojibake"] += 1
        elif len(jd_text) > max_jd_length:
            jd_text = jd_text[:max_jd_length].rstrip()
            stats["jd_truncated"] += 1

        if jd_text != old_jd:
            updates["jd_text"] = jd_text
            updates["description"] = jd_text
            updates["jd_text_length"] = len(jd_text)
            stats["jd_cleaned"] += 1

        fetch_status = updates.get("fetch_status", row["fetch_status"] or "")
        normalized_url = updates.get("normalized_url", row["normalized_url"] or "")
        if row["is_current"] == 1:
            if not jd_text and fetch_status != "content_empty":
                updates["fetch_status"] = "content_empty"
            elif jd_text and normalized_url and fetch_status == "content_empty":
                updates["fetch_status"] = "success"

        if not keep_raw_json and row["raw_json"]:
            updates["raw_json"] = ""
            stats["raw_json_cleared"] += 1

        ats_date_info = compute_ats_date_info(
            ats_published_at=row["ats_published_at"],
            ats_updated_at=row["ats_updated_at"],
            raw_json=row["raw_json"],
        )
        updates["ats_date_normalized"] = ats_date_info.normalized
        updates["ats_date_source"] = ats_date_info.source
        updates["ats_age_days"] = ats_date_info.age_days
        updates["ats_age_bucket"] = ats_date_info.bucket

        apac_value = is_apac_job(
            updates.get("location_normalized", row["location_normalized"]),
            updates.get("location_raw", row["location_raw"]),
            updates.get("matched_location_keywords", row["matched_location_keywords"]),
            updates.get("title", row["title"]),
            jd_text,
        )
        updates["is_apac"] = apac_value
        if apac_value:
            stats["is_apac_marked"] += 1

        if updates:
            set_clause = ", ".join(f"{column} = ?" for column in updates)
            params = [*updates.values(), row["id"]]
            conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", params)

    return stats


def clean_small_text(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = strip_control_chars(text)
    return normalize_whitespace(text)


def clean_jd_text(value: object) -> str:
    text = html_to_text(value)
    text = html.unescape(text)
    text = strip_control_chars(text)
    return normalize_whitespace(text)


def strip_control_chars(text: str) -> str:
    return "".join(
        char if char in "\n\t" or ord(char) >= 32 else " "
        for char in text
    )


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_empty_jd(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized in EMPTY_JD_VALUES:
        return True
    return bool(normalized) and not re.search(r"[\w\u4e00-\u9fff]", normalized)


def is_mojibake(text: str) -> bool:
    if "\ufffd" in text or "�" in text:
        return True
    marker_hits = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    if marker_hits >= 3:
        return True
    if len(text) > 0 and marker_hits / max(len(text), 1) > 0.01:
        return True
    return False


def export_csvs(conn: sqlite3.Connection, export_dir: Path) -> None:
    for table in EXPORT_TABLES:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        column_names = [description[0] for description in conn.execute(
            f"SELECT * FROM {table} LIMIT 0"
        ).description]
        path = export_dir / f"{table}.csv"
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(column_names)
            for row in rows:
                writer.writerow([row[column] for column in column_names])
        print(f"Exported {table}: {len(rows)} rows -> {path}")


if __name__ == "__main__":
    raise SystemExit(main())
