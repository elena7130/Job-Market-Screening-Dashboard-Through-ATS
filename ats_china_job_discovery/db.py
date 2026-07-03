from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discovered_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ats_type TEXT,
            ats_token TEXT,
            company_name_guess TEXT,
            sample_url TEXT,
            discovered_keyword TEXT,
            source_query TEXT,
            discovered_at TEXT,
            api_status TEXT,
            api_error TEXT,
            total_open_jobs INTEGER,
            china_keyword_hits INTEGER,
            recent_china_keyword_hits INTEGER,
            last_checked_at TEXT,
            UNIQUE(ats_type, ats_token)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT,
            ats_type TEXT,
            ats_token TEXT,
            ats_job_id TEXT,
            title TEXT,
            location_raw TEXT,
            description TEXT,
            jd_text TEXT,
            jd_text_length INTEGER,
            department TEXT,
            url TEXT,
            normalized_url TEXT,
            fetch_status TEXT,
            ats_board_token TEXT,
            ats_published_at TEXT,
            ats_updated_at TEXT,
            first_seen_at TEXT,
            last_seen_at TEXT,
            fetched_at TEXT,
            is_current INTEGER,
            recency_status TEXT,
            matched_location_keywords TEXT,
            raw_json TEXT,
            UNIQUE(ats_type, ats_token, ats_job_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            source_query TEXT,
            result_url TEXT,
            result_title TEXT,
            discovered_keyword TEXT,
            ats_type TEXT,
            ats_token TEXT,
            company_name_guess TEXT,
            url_kind TEXT,
            status TEXT,
            discovered_at TEXT,
            reviewed_at TEXT,
            notes TEXT,
            UNIQUE(result_url)
        )
        """
    )
    _ensure_jobs_columns(conn)
    _ensure_discovery_candidate_columns(conn)
    _backfill_jobs_columns(conn)
    conn.commit()


def _ensure_jobs_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    column_defs = {
        "jd_text": "TEXT",
        "jd_text_length": "INTEGER",
        "normalized_url": "TEXT",
        "fetch_status": "TEXT",
        "ats_board_token": "TEXT",
    }
    for column, column_type in column_defs.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {column_type}")


def _backfill_jobs_columns(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET jd_text = COALESCE(jd_text, description, ''),
            jd_text_length = COALESCE(jd_text_length, LENGTH(COALESCE(jd_text, description, ''))),
            normalized_url = COALESCE(normalized_url, url, ''),
            fetch_status = COALESCE(fetch_status, CASE WHEN is_current = 1 THEN 'success' ELSE 'closed' END),
            ats_board_token = COALESCE(ats_board_token, ats_token, '')
        """
    )


def _ensure_discovery_candidate_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(discovery_candidates)").fetchall()
    }
    if "url_kind" not in existing_columns:
        conn.execute("ALTER TABLE discovery_candidates ADD COLUMN url_kind TEXT")


def upsert_discovered_company(conn: sqlite3.Connection, company: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO discovered_companies (
            ats_type, ats_token, company_name_guess, sample_url, discovered_keyword,
            source_query, discovered_at, api_status, api_error, total_open_jobs,
            china_keyword_hits, recent_china_keyword_hits, last_checked_at
        )
        VALUES (
            :ats_type, :ats_token, :company_name_guess, :sample_url, :discovered_keyword,
            :source_query, :discovered_at, 'pending', NULL, 0, 0, 0, NULL
        )
        ON CONFLICT(ats_type, ats_token) DO UPDATE SET
            company_name_guess = COALESCE(discovered_companies.company_name_guess, excluded.company_name_guess),
            sample_url = COALESCE(discovered_companies.sample_url, excluded.sample_url),
            discovered_keyword = COALESCE(discovered_companies.discovered_keyword, excluded.discovered_keyword),
            source_query = COALESCE(discovered_companies.source_query, excluded.source_query)
        """,
        company,
    )
    conn.commit()


def list_discovered_companies(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT *
        FROM discovered_companies
        ORDER BY ats_type, ats_token
        """
    ).fetchall()
    return list(rows)


def get_first_seen_at(
    conn: sqlite3.Connection, ats_type: str, ats_token: str, ats_job_id: str
) -> str | None:
    row = conn.execute(
        """
        SELECT first_seen_at
        FROM jobs
        WHERE ats_type = ? AND ats_token = ? AND ats_job_id = ?
        """,
        (ats_type, ats_token, ats_job_id),
    ).fetchone()
    return row["first_seen_at"] if row else None


def upsert_job(conn: sqlite3.Connection, job: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            company_name, ats_type, ats_token, ats_job_id, title, location_raw,
            description, jd_text, jd_text_length, department, url, normalized_url,
            fetch_status, ats_board_token, ats_published_at, ats_updated_at, first_seen_at,
            last_seen_at, fetched_at, is_current, recency_status, matched_location_keywords,
            raw_json
        )
        VALUES (
            :company_name, :ats_type, :ats_token, :ats_job_id, :title, :location_raw,
            :description, :jd_text, :jd_text_length, :department, :url, :normalized_url,
            :fetch_status, :ats_board_token, :ats_published_at, :ats_updated_at,
            :first_seen_at, :last_seen_at, :fetched_at, :is_current, :recency_status,
            :matched_location_keywords, :raw_json
        )
        ON CONFLICT(ats_type, ats_token, ats_job_id) DO UPDATE SET
            company_name = excluded.company_name,
            title = excluded.title,
            location_raw = excluded.location_raw,
            description = excluded.description,
            jd_text = excluded.jd_text,
            jd_text_length = excluded.jd_text_length,
            department = excluded.department,
            url = excluded.url,
            normalized_url = excluded.normalized_url,
            fetch_status = excluded.fetch_status,
            ats_board_token = excluded.ats_board_token,
            ats_published_at = excluded.ats_published_at,
            ats_updated_at = excluded.ats_updated_at,
            first_seen_at = jobs.first_seen_at,
            last_seen_at = excluded.last_seen_at,
            fetched_at = excluded.fetched_at,
            is_current = excluded.is_current,
            recency_status = excluded.recency_status,
            matched_location_keywords = excluded.matched_location_keywords,
            raw_json = excluded.raw_json
        """,
        job,
    )


def mark_missing_jobs_not_current(
    conn: sqlite3.Connection, ats_type: str, ats_token: str, current_job_ids: set[str]
) -> None:
    if current_job_ids:
        placeholders = ",".join("?" for _ in current_job_ids)
        params = [ats_type, ats_token, *sorted(current_job_ids)]
        conn.execute(
            f"""
            UPDATE jobs
            SET is_current = 0,
                fetch_status = 'closed'
            WHERE ats_type = ?
              AND ats_token = ?
              AND ats_job_id NOT IN ({placeholders})
            """,
            params,
        )
    else:
        conn.execute(
            """
            UPDATE jobs
            SET is_current = 0,
                fetch_status = 'closed'
            WHERE ats_type = ? AND ats_token = ?
            """,
            (ats_type, ats_token),
        )


def update_company_status(
    conn: sqlite3.Connection,
    ats_type: str,
    ats_token: str,
    *,
    api_status: str,
    api_error: str | None,
    total_open_jobs: int,
    china_keyword_hits: int,
    recent_china_keyword_hits: int,
    last_checked_at: str,
) -> None:
    conn.execute(
        """
        UPDATE discovered_companies
        SET api_status = ?,
            api_error = ?,
            total_open_jobs = ?,
            china_keyword_hits = ?,
            recent_china_keyword_hits = ?,
            last_checked_at = ?
        WHERE ats_type = ? AND ats_token = ?
        """,
        (
            api_status,
            api_error,
            total_open_jobs,
            china_keyword_hits,
            recent_china_keyword_hits,
            last_checked_at,
            ats_type,
            ats_token,
        ),
    )
    conn.commit()


def count_api_success_companies(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM discovered_companies WHERE api_status = 'success'"
    ).fetchone()
    return int(row["count"])


def count_current_keyword_jobs(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM jobs
        WHERE is_current = 1
          AND COALESCE(matched_location_keywords, '') <> ''
        """
    ).fetchone()
    return int(row["count"])


def upsert_discovery_candidate(
    conn: sqlite3.Connection, candidate: dict[str, Any]
) -> None:
    conn.execute(
        """
        INSERT INTO discovery_candidates (
            source, source_query, result_url, result_title, discovered_keyword,
            ats_type, ats_token, company_name_guess, url_kind, status, discovered_at,
            reviewed_at, notes
        )
        VALUES (
            :source, :source_query, :result_url, :result_title, :discovered_keyword,
            :ats_type, :ats_token, :company_name_guess, :url_kind, :status, :discovered_at,
            NULL, :notes
        )
        ON CONFLICT(result_url) DO UPDATE SET
            source = excluded.source,
            source_query = excluded.source_query,
            result_title = excluded.result_title,
            discovered_keyword = excluded.discovered_keyword,
            ats_type = excluded.ats_type,
            ats_token = excluded.ats_token,
            company_name_guess = excluded.company_name_guess,
            url_kind = excluded.url_kind,
            status = CASE
                WHEN discovery_candidates.status IN ('accepted', 'rejected') THEN discovery_candidates.status
                ELSE excluded.status
            END,
            notes = excluded.notes
        """,
        candidate,
    )


def update_discovery_candidate_review(
    conn: sqlite3.Connection, result_url: str, status: str, reviewed_at: str
) -> None:
    conn.execute(
        """
        UPDATE discovery_candidates
        SET status = ?,
            reviewed_at = ?
        WHERE result_url = ?
        """,
        (status, reviewed_at, result_url),
    )


def list_discovery_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT *
        FROM discovery_candidates
        ORDER BY discovered_at DESC, source_query, result_url
        """
    ).fetchall()
    return list(rows)
