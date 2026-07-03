from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import db
from parsers import classify_ats_url_kind, parse_ats_url


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_QUERIES = BASE_DIR / "data" / "search_queries.csv"
DEFAULT_REVIEW_EXPORT = BASE_DIR / "output" / "review" / "discovery_candidates.csv"
DEFAULT_DB = BASE_DIR / "output" / "ats_jobs.db"
DEFAULT_SEARCH_RESULTS = BASE_DIR / "data" / "search_results.csv"

SEARCHAPI_URL = "https://www.searchapi.io/api/v1/search"
USER_AGENT = "ats-china-job-discovery/0.1 (candidate discovery)"

SEARCH_RESULTS_COLUMNS = [
    "source_query",
    "result_url",
    "result_title",
    "discovered_keyword",
]

REVIEW_COLUMNS = [
    "status",
    "source",
    "source_query",
    "result_url",
    "result_title",
    "discovered_keyword",
    "ats_type",
    "ats_token",
    "company_name_guess",
    "url_kind",
    "discovered_at",
    "reviewed_at",
    "notes",
]


def main() -> int:
    args = parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(Path(args.db))
    db.init_db(conn)

    if args.export_only:
        exported = export_review(conn, Path(args.review_export))
        print(f"Review export rows: {exported}")
        print(f"Review file: {args.review_export}")
        return 0

    if args.import_review:
        imported = import_review(
            conn,
            Path(args.import_review),
            Path(args.search_results),
        )
        export_review(conn, Path(args.review_export))
        print(f"Imported review rows: {imported}")
        print(f"Updated search results: {args.search_results}")
        return 0

    queries = read_queries(Path(args.queries))
    if queries.empty:
        print(f"No enabled queries found in {args.queries}")
        export_review(conn, Path(args.review_export))
        return 0

    api_key = os.getenv("SEARCHAPI_API_KEY", "").strip()
    if not api_key:
        print("SEARCHAPI_API_KEY is not set.")
        print("Set it first, or run with --export-only to only export existing candidates.")
        export_review(conn, Path(args.review_export))
        return 1

    existing_tokens = load_existing_tokens(conn, Path(args.search_results))
    inserted = 0
    unsupported = 0
    for query in queries.to_dict("records"):
        results = search_google(
            api_key=api_key,
            query=query["query_text"],
            limit=args.limit,
        )
        for result in results:
            candidate = build_candidate(result, query, existing_tokens)
            db.upsert_discovery_candidate(conn, candidate)
            inserted += 1
            if candidate["status"] == "unsupported":
                unsupported += 1
        conn.commit()

    exported = export_review(conn, Path(args.review_export))
    print(f"Queries run: {len(queries)}")
    print(f"Candidates upserted: {inserted}")
    print(f"Unsupported candidates: {unsupported}")
    print(f"Review export rows: {exported}")
    print(f"Review file: {args.review_export}")
    conn.close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover ATS job-board URL candidates using a search API."
    )
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--review-export", default=str(DEFAULT_REVIEW_EXPORT))
    parser.add_argument("--search-results", default=str(DEFAULT_SEARCH_RESULTS))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--import-review",
        help="Import reviewed discovery_candidates.csv and append accepted rows to search_results.csv.",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Only export existing candidates; does not call the search API.",
    )
    return parser.parse_args()


def read_queries(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Query CSV not found: {path}")
    df = read_csv_flexible(path)
    required = {"query_text"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Query CSV missing columns: {', '.join(sorted(missing))}")
    if "enabled" not in df.columns:
        df["enabled"] = "1"
    if "discovered_keyword" not in df.columns:
        df["discovered_keyword"] = ""
    return df[df["enabled"].astype(str).str.lower().isin({"1", "true", "yes", "y"})]


def search_google(api_key: str, query: str, limit: int) -> list[dict[str, Any]]:
    response = requests.get(
        SEARCHAPI_URL,
        params={
            "engine": "google",
            "q": query,
            "num": limit,
            "api_key": api_key,
        },
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    organic_results = data.get("organic_results") or []
    if not isinstance(organic_results, list):
        return []
    return organic_results


def build_candidate(
    result: dict[str, Any],
    query: dict[str, Any],
    existing_tokens: set[tuple[str, str]],
) -> dict[str, Any]:
    result_url = str(result.get("link") or result.get("url") or "").strip()
    result_title = str(result.get("title") or "").strip()
    parsed = parse_ats_url(result_url)
    url_kind = classify_ats_url_kind(result_url)
    status = "unsupported"
    notes = "URL is not a supported ATS job-board URL."
    ats_type = ""
    ats_token = ""
    company_name_guess = ""
    if parsed:
        ats_type = parsed.ats_type
        ats_token = parsed.ats_token
        company_name_guess = parsed.company_name_guess
        if (ats_type, ats_token) in existing_tokens:
            status = "duplicate"
            notes = "ATS company already exists in search_results.csv or discovered_companies."
        elif url_kind == "company_page":
            status = "review_company_page"
            notes = "Supported ATS company page. Accept if this company is relevant."
        else:
            status = "pending"
            notes = ""

    return {
        "source": "searchapi_google",
        "source_query": query["query_text"],
        "result_url": result_url,
        "result_title": result_title,
        "discovered_keyword": query.get("discovered_keyword", ""),
        "ats_type": ats_type,
        "ats_token": ats_token,
        "company_name_guess": company_name_guess,
        "url_kind": url_kind,
        "status": status,
        "discovered_at": now_iso(),
        "notes": notes,
    }


def load_existing_tokens(
    conn: Any, search_results_path: Path
) -> set[tuple[str, str]]:
    tokens: set[tuple[str, str]] = set()
    for row in db.list_discovered_companies(conn):
        tokens.add((row["ats_type"], row["ats_token"]))

    if search_results_path.exists():
        df = pd.read_csv(search_results_path, dtype=str).fillna("")
        if "result_url" in df.columns:
            for url in df["result_url"]:
                parsed = parse_ats_url(url)
                if parsed:
                    tokens.add((parsed.ats_type, parsed.ats_token))
    return tokens


def export_review(conn: Any, path: Path) -> int:
    refresh_candidate_url_kinds(conn)
    rows = [dict(row) for row in db.list_discovery_candidates(conn)]
    df = pd.DataFrame(rows)
    df = df.reindex(columns=REVIEW_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_csv_with_fallback(df, path)
    return len(df)


def write_csv_with_fallback(df: pd.DataFrame, path: Path) -> Path:
    try:
        df.to_csv(path, index=False)
        return path
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_path = path.with_name(f"{path.stem}_{timestamp}{path.suffix}")
        df.to_csv(fallback_path, index=False)
        print(f"Could not overwrite locked file: {path}")
        print(f"Wrote fallback review export instead: {fallback_path}")
        return fallback_path


def refresh_candidate_url_kinds(conn: Any) -> None:
    rows = conn.execute(
        "SELECT result_url, status FROM discovery_candidates"
    ).fetchall()
    for row in rows:
        result_url = row["result_url"]
        status = row["status"]
        url_kind = classify_ats_url_kind(result_url)
        if status == "pending" and url_kind == "company_page":
            conn.execute(
                """
                UPDATE discovery_candidates
                SET url_kind = ?,
                    status = 'review_company_page',
                    notes = 'Supported ATS company page. Accept if this company is relevant.'
                WHERE result_url = ?
                """,
                (url_kind, result_url),
            )
        else:
            conn.execute(
                """
                UPDATE discovery_candidates
                SET url_kind = ?
                WHERE result_url = ?
                """,
                (url_kind, result_url),
            )
    conn.commit()


def import_review(
    conn: Any, review_path: Path, search_results_path: Path
) -> int:
    if not review_path.exists():
        raise FileNotFoundError(f"Review CSV not found: {review_path}")
    review_df = read_csv_flexible(review_path)
    required = {"status", "result_url", "source_query", "result_title", "discovered_keyword"}
    missing = required - set(review_df.columns)
    if missing:
        raise ValueError(f"Review CSV missing columns: {', '.join(sorted(missing))}")

    reviewed_at = now_iso()
    imported = 0
    for row in review_df.to_dict("records"):
        status = row.get("status", "").strip().lower()
        if status not in {
            "pending",
            "accepted",
            "rejected",
            "duplicate",
            "unsupported",
            "review_company_page",
        }:
            continue
        db.update_discovery_candidate_review(
            conn, row.get("result_url", ""), status, reviewed_at
        )
        if status == "accepted":
            imported += 1

    conn.commit()
    append_accepted_to_search_results(review_df, search_results_path)
    return imported


def append_accepted_to_search_results(
    review_df: pd.DataFrame, search_results_path: Path
) -> None:
    accepted = review_df[review_df["status"].str.lower() == "accepted"].copy()
    if accepted.empty:
        return

    accepted_rows = pd.DataFrame(
        {
            "source_query": accepted["source_query"],
            "result_url": accepted["result_url"],
            "result_title": accepted["result_title"],
            "discovered_keyword": accepted["discovered_keyword"],
        }
    )

    if search_results_path.exists():
        current = read_csv_flexible(search_results_path)
    else:
        current = pd.DataFrame(columns=SEARCH_RESULTS_COLUMNS)

    current = current.reindex(columns=SEARCH_RESULTS_COLUMNS).fillna("")
    combined = pd.concat([current, accepted_rows], ignore_index=True)
    combined = combined.drop_duplicates(subset=["result_url"], keep="first")
    search_results_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(search_results_path, index=False, encoding="utf-8-sig")


def read_csv_flexible(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp1252", "gb18030", "latin1"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.read_csv(path, dtype=str).fillna("")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
