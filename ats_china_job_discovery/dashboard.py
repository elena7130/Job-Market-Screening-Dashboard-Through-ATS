from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd
import requests
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "output" / "ats_jobs.clean.db"
RECENT_STATUSES = {"recent_published", "recent_updated", "newly_seen"}

JOB_COLUMNS = [
    "id",
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
    "imported_at",
]

COMPANY_COLUMNS = [
    "id",
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
    "imported_at",
]


def main() -> None:
    st.set_page_config(
        page_title="China Job Market Dashboard",
        page_icon=":mag:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()

    st.title("China Job Market Dashboard")
    st.caption("A focused ATS-based job board for China, APAC, Europe, and remote roles.")

    data_source = get_data_source()
    jobs_df, companies_df = load_dashboard_data(data_source)
    jobs_df = normalize_jobs(jobs_df)
    companies_df = normalize_companies(companies_df)

    render_source_status(data_source, jobs_df, companies_df)
    render_summary(jobs_df, companies_df)

    jobs_tab, companies_tab = st.tabs(["Jobs", "Companies"])
    with jobs_tab:
        render_jobs_tab(jobs_df)
    with companies_tab:
        render_companies_tab(companies_df)


def get_data_source() -> dict[str, str]:
    supabase_url = get_secret("SUPABASE_URL")
    supabase_key = get_secret("SUPABASE_ANON_KEY")
    jobs_table = get_secret("SUPABASE_JOBS_TABLE") or "china_jobs"
    companies_table = get_secret("SUPABASE_COMPANIES_TABLE") or "china_companies"

    if supabase_url and supabase_key:
        return {
            "type": "supabase",
            "label": "Supabase",
            "url": supabase_url.rstrip("/"),
            "key": supabase_key,
            "jobs_table": jobs_table,
            "companies_table": companies_table,
        }

    return {
        "type": "sqlite",
        "label": "Local SQLite",
        "db_path": str(DEFAULT_DB),
    }


def get_secret(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, "")).strip()


@st.cache_data(show_spinner="Loading dashboard data...", ttl=300)
def load_dashboard_data(data_source: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if data_source["type"] == "supabase":
        jobs_df = load_supabase_table(
            data_source["url"],
            data_source["key"],
            data_source["jobs_table"],
            JOB_COLUMNS,
            order="last_seen_at.desc",
        )
        companies_df = load_supabase_table(
            data_source["url"],
            data_source["key"],
            data_source["companies_table"],
            COMPANY_COLUMNS,
            order="recent_china_keyword_hits.desc",
        )
        return jobs_df, companies_df

    db_path = Path(data_source["db_path"])
    if not db_path.exists():
        return pd.DataFrame(columns=JOB_COLUMNS), pd.DataFrame(columns=COMPANY_COLUMNS)

    return load_sqlite_data(db_path)


def load_supabase_table(
    supabase_url: str,
    supabase_key: str,
    table: str,
    columns: list[str],
    *,
    order: str,
    page_size: int = 1000,
    max_rows: int = 50000,
) -> pd.DataFrame:
    endpoint = f"{supabase_url}/rest/v1/{table}"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }
    rows: list[dict[str, Any]] = []

    for offset in range(0, max_rows, page_size):
        params = {
            "select": ",".join(columns),
            "order": order,
            "limit": str(page_size),
            "offset": str(offset),
        }
        response = requests.get(endpoint, headers=headers, params=params, timeout=30)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase request failed for {table}: "
                f"{response.status_code} {response.text[:500]}"
            )
        batch = response.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break

    return pd.DataFrame(rows, columns=columns)


def load_sqlite_data(db_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    read_only_uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(read_only_uri, uri=True, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        jobs_df = pd.read_sql_query(
            """
            SELECT id, company_name, ats_type, ats_token, ats_board_token, ats_job_id,
                   title, location_raw, location_normalized, is_china, is_europe,
                   is_remote, recency_status, fetch_status, ats_published_at,
                   ats_updated_at, ats_date_normalized, ats_date_source, ats_age_days,
                   ats_age_bucket, first_seen_at, last_seen_at, fetched_at,
                   matched_location_keywords, normalized_url, url, jd_text_length,
                   jd_text
            FROM jobs
            WHERE is_current = 1
            ORDER BY last_seen_at DESC, company_name, title
            """,
            conn,
        )
        companies_df = pd.read_sql_query(
            """
            SELECT id, company_name_guess, ats_type, ats_token, api_status, api_error,
                   total_open_jobs, china_keyword_hits, recent_china_keyword_hits,
                   sample_url, discovered_keyword, source_query, discovered_at,
                   last_checked_at
            FROM discovered_companies
            ORDER BY recent_china_keyword_hits DESC, china_keyword_hits DESC,
                     company_name_guess, ats_type, ats_token
            """,
            conn,
        )
    return jobs_df, companies_df


def normalize_jobs(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_columns(df, JOB_COLUMNS)
    df = df.fillna("")

    for column in ["is_china", "is_europe", "is_remote"]:
        df[column] = df[column].apply(to_bool)

    df["is_apac"] = df["is_china"] | df["matched_location_keywords"].astype(str).str.contains(
        "APAC|Asia|Asia Pacific", case=False, na=False
    )
    df["is_recent"] = df["recency_status"].isin(RECENT_STATUSES)
    df["display_location"] = df["location_normalized"].where(
        df["location_normalized"].astype(str).str.len() > 0,
        df["location_raw"],
    )
    df["job_url"] = df["normalized_url"].where(
        df["normalized_url"].astype(str).str.len() > 0,
        df["url"],
    )
    df["company_name"] = df["company_name"].replace("", "Unknown company")
    df["title"] = df["title"].replace("", "Untitled role")

    numeric_columns = ["ats_age_days", "jd_text_length"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return df


def normalize_companies(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_columns(df, COMPANY_COLUMNS)
    df = df.fillna("")

    for column in ["total_open_jobs", "china_keyword_hits", "recent_china_keyword_hits"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)

    df["company_name_guess"] = df["company_name_guess"].replace("", "Unknown company")
    return df


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df.loc[:, columns]


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def render_source_status(
    data_source: dict[str, str], jobs_df: pd.DataFrame, companies_df: pd.DataFrame
) -> None:
    if data_source["type"] == "supabase":
        imported_values = pd.concat(
            [
                jobs_df["imported_at"].astype(str),
                companies_df["imported_at"].astype(str),
            ],
            ignore_index=True,
        )
        imported_values = imported_values[imported_values.str.len() > 0]
        last_imported = imported_values.max() if not imported_values.empty else "Unknown"
        st.info(
            f"Data source: Supabase | Jobs table: `{data_source['jobs_table']}` | "
            f"Companies table: `{data_source['companies_table']}` | "
            f"Last import: {last_imported}"
        )
        return

    db_path = Path(data_source["db_path"])
    if db_path.exists():
        st.info(f"Data source: Local SQLite | `{db_path}`")
    else:
        st.warning(
            "No Supabase credentials are configured and the local SQLite database was "
            f"not found at `{db_path}`."
        )


def render_summary(jobs_df: pd.DataFrame, companies_df: pd.DataFrame) -> None:
    keyword_jobs = int(
        jobs_df["matched_location_keywords"].astype(str).str.len().gt(0).sum()
    ) if not jobs_df.empty else 0
    recent_jobs = int(jobs_df["is_recent"].sum()) if not jobs_df.empty else 0
    china_jobs = int(jobs_df["is_china"].sum()) if not jobs_df.empty else 0
    remote_jobs = int(jobs_df["is_remote"].sum()) if not jobs_df.empty else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Jobs", f"{len(jobs_df):,}")
    col2.metric("Recent", f"{recent_jobs:,}")
    col3.metric("China", f"{china_jobs:,}")
    col4.metric("Remote", f"{remote_jobs:,}")
    col5.metric("Companies", f"{len(companies_df):,}")

    st.caption(f"Keyword-matched roles: {keyword_jobs:,}")


def render_jobs_tab(jobs_df: pd.DataFrame) -> None:
    if jobs_df.empty:
        st.info("No jobs found. Sync data to Supabase or run the local collector first.")
        return

    filtered_df = filter_jobs(jobs_df)
    render_jobs_table(filtered_df)
    st.divider()
    render_job_detail(filtered_df)


def filter_jobs(jobs_df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("Filters")
        search_text = st.text_input(
            "Search",
            placeholder="Company, title, location, keyword, JD...",
        ).strip()

        only_recent = st.toggle("Recent roles only", value=False)
        only_keyword = st.toggle("Keyword matches only", value=True)
        china_only = st.toggle("China only", value=False)
        apac_only = st.toggle("APAC only", value=False)
        europe_only = st.toggle("Europe only", value=False)
        remote_only = st.toggle("Remote only", value=False)

        ats_filter = st.multiselect("ATS platform", options_for(jobs_df, "ats_type"))
        recency_filter = st.multiselect("Recency", options_for(jobs_df, "recency_status"))
        age_bucket_filter = st.multiselect(
            "ATS age bucket",
            ordered_age_buckets(jobs_df),
            default=[
                bucket
                for bucket in ["0-7 days", "8-14 days", "15-30 days"]
                if bucket in set(jobs_df["ats_age_bucket"].astype(str))
            ],
        )

        company_filter = st.multiselect(
            "Company",
            options_for(jobs_df, "company_name"),
            max_selections=25,
        )
        location_filter = st.multiselect(
            "Location",
            options_for(jobs_df, "display_location"),
            max_selections=25,
        )
        max_rows = st.number_input(
            "Rows to display",
            min_value=50,
            max_value=5000,
            value=1000,
            step=50,
        )

    df = jobs_df.copy()
    if only_recent:
        df = df[df["is_recent"]]
    if only_keyword:
        df = df[df["matched_location_keywords"].astype(str).str.len() > 0]
    if china_only:
        df = df[df["is_china"]]
    if apac_only:
        df = df[df["is_apac"]]
    if europe_only:
        df = df[df["is_europe"]]
    if remote_only:
        df = df[df["is_remote"]]
    if ats_filter:
        df = df[df["ats_type"].isin(ats_filter)]
    if recency_filter:
        df = df[df["recency_status"].isin(recency_filter)]
    if age_bucket_filter:
        df = df[df["ats_age_bucket"].astype(str).isin(age_bucket_filter)]
    if company_filter:
        df = df[df["company_name"].isin(company_filter)]
    if location_filter:
        df = df[df["display_location"].isin(location_filter)]
    if search_text:
        search_columns = [
            "company_name",
            "title",
            "location_raw",
            "location_normalized",
            "matched_location_keywords",
            "jd_text",
        ]
        mask = pd.Series(False, index=df.index)
        for column in search_columns:
            mask |= df[column].astype(str).str.contains(
                search_text, case=False, na=False, regex=False
            )
        df = df[mask]

    st.session_state["jobs_display_limit"] = int(max_rows)
    return df.sort_values(
        by=["last_seen_at", "company_name", "title"],
        ascending=[False, True, True],
    )


def render_jobs_table(filtered_df: pd.DataFrame) -> None:
    limit = st.session_state.get("jobs_display_limit", 1000)
    st.subheader("Job Results")
    st.write(f"{len(filtered_df):,} matching roles")

    display_columns = [
        "company_name",
        "title",
        "display_location",
        "is_china",
        "is_apac",
        "is_europe",
        "is_remote",
        "recency_status",
        "ats_age_bucket",
        "ats_type",
        "job_url",
    ]
    display_df = filtered_df.head(limit).loc[:, display_columns].rename(
        columns={
            "company_name": "Company",
            "title": "Role",
            "display_location": "Location",
            "is_china": "China",
            "is_apac": "APAC",
            "is_europe": "Europe",
            "is_remote": "Remote",
            "recency_status": "Recency",
            "ats_age_bucket": "Age",
            "ats_type": "ATS",
            "job_url": "Link",
        }
    )

    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        height=620,
        column_config={
            "Link": st.column_config.LinkColumn("Link", display_text="Open"),
        },
    )

    export_columns = [column for column in JOB_COLUMNS if column in filtered_df.columns]
    csv = filtered_df.loc[:, export_columns].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Download filtered CSV",
        data=csv,
        file_name="filtered_jobs.csv",
        mime="text/csv",
    )


def render_job_detail(filtered_df: pd.DataFrame) -> None:
    st.subheader("Job Detail")
    if filtered_df.empty:
        st.info("No roles match the current filters.")
        return

    detail_df = filtered_df.head(st.session_state.get("jobs_display_limit", 1000))
    labels = {make_job_label(row): row["id"] for _, row in detail_df.iterrows()}
    selected_label = st.selectbox("Select a role", list(labels.keys()))
    selected_id = labels[selected_label]
    row = detail_df[detail_df["id"] == selected_id].iloc[0]

    header_left, header_right = st.columns([0.72, 0.28], gap="large")
    with header_left:
        st.markdown(f"### {row['title']}")
        st.write(row["company_name"])
        st.write(row["display_location"] or "Unknown location")

    with header_right:
        url = str(row["job_url"] or "")
        if url:
            st.link_button("Open job posting", url)

    detail_fields = {
        "Recency": row["recency_status"],
        "Matched keywords": row["matched_location_keywords"],
        "Published": row["ats_published_at"],
        "Updated": row["ats_updated_at"],
        "ATS date": row["ats_date_normalized"],
        "ATS date source": row["ats_date_source"],
        "ATS age": row["ats_age_bucket"],
        "First seen": row["first_seen_at"],
        "Last seen": row["last_seen_at"],
        "ATS platform": row["ats_type"],
    }
    field_columns = st.columns(5)
    for index, (label, value) in enumerate(detail_fields.items()):
        with field_columns[index % len(field_columns)]:
            st.text_input(label, value=str(value or ""), disabled=True)

    st.text_area(
        "Job description",
        value=str(row["jd_text"] or ""),
        height=520,
        disabled=True,
    )


def make_job_label(row: pd.Series) -> str:
    company = str(row.get("company_name") or "Unknown company")
    title = str(row.get("title") or "Untitled role")
    location = str(row.get("display_location") or "")
    job_id = row.get("id")
    pieces = [company, title]
    if location:
        pieces.append(location)
    pieces.append(f"#{job_id}")
    return " | ".join(pieces)


def render_companies_tab(companies_df: pd.DataFrame) -> None:
    st.subheader("Companies")
    if companies_df.empty:
        st.info("No companies found.")
        return

    col1, col2 = st.columns([0.35, 0.65])
    with col1:
        status_filter = st.multiselect("API status", options_for(companies_df, "api_status"))
    with col2:
        only_hits = st.toggle("Companies with China/APAC hits only", value=True)

    df = companies_df.copy()
    if status_filter:
        df = df[df["api_status"].isin(status_filter)]
    if only_hits:
        df = df[df["china_keyword_hits"] > 0]

    st.write(f"{len(df):,} matching companies")
    display_columns = [
        "company_name_guess",
        "ats_type",
        "ats_token",
        "api_status",
        "total_open_jobs",
        "china_keyword_hits",
        "recent_china_keyword_hits",
        "last_checked_at",
        "sample_url",
    ]
    display_df = df.loc[:, display_columns].rename(
        columns={
            "company_name_guess": "Company",
            "ats_type": "ATS",
            "ats_token": "Token",
            "api_status": "API status",
            "total_open_jobs": "Open roles",
            "china_keyword_hits": "China/APAC hits",
            "recent_china_keyword_hits": "Recent hits",
            "last_checked_at": "Last checked",
            "sample_url": "Sample URL",
        }
    )
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        height=620,
        column_config={
            "Sample URL": st.column_config.LinkColumn("Sample URL", display_text="Open"),
        },
    )


def options_for(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns:
        return []
    return sorted(value for value in df[column].dropna().astype(str).unique() if value)


def ordered_age_buckets(df: pd.DataFrame) -> list[str]:
    available = set(df["ats_age_bucket"].dropna().astype(str))
    ordered = [
        "0-7 days",
        "8-14 days",
        "15-30 days",
        "31-60 days",
        "60+ days",
        "unknown",
    ]
    return [bucket for bucket in ordered if bucket in available]


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
        }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 14px 16px;
        }
        div[data-testid="stMetric"] label {
            color: #475569;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
