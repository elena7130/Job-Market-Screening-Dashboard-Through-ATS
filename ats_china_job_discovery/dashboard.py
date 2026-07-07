from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "output" / "ats_jobs.clean.db"

JOB_COLUMNS = [
    "id",
    "company_name",
    "title",
    "location_raw",
    "location_normalized",
    "is_apac",
    "ats_type",
    "ats_board_token",
    "recency_status",
    "fetch_status",
    "is_current",
    "matched_location_keywords",
    "ats_published_at",
    "ats_updated_at",
    "ats_date_normalized",
    "ats_date_source",
    "ats_age_days",
    "ats_age_bucket",
    "first_seen_at",
    "last_seen_at",
    "jd_text_length",
    "normalized_url",
    "url",
    "jd_text",
]


def main() -> None:
    st.set_page_config(
        page_title="ATS China Job Dashboard",
        page_icon="🔎",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("ATS China Job Dashboard")
    st.caption("本地读取 SQLite 数据库，用于快速筛选 China/APAC 相关岗位。")

    db_path = Path(
        st.sidebar.text_input("SQLite 数据库路径", value=str(DEFAULT_DB))
    ).expanduser()
    if not db_path.exists():
        st.error(f"数据库不存在: {db_path}")
        st.stop()

    db_mtime = db_path.stat().st_mtime
    jobs_df = load_jobs(str(db_path), db_mtime)
    companies_df = load_companies(str(db_path), db_mtime)
    candidates_df = load_candidates(str(db_path), db_mtime)

    show_summary(jobs_df, companies_df, candidates_df)

    jobs_tab, companies_tab, candidates_tab = st.tabs(
        ["岗位筛选", "公司汇总", "候选 URL"]
    )
    with jobs_tab:
        render_jobs_tab(jobs_df)
    with companies_tab:
        render_companies_tab(companies_df)
    with candidates_tab:
        render_candidates_tab(candidates_df)


@st.cache_data(show_spinner=False)
def load_jobs(db_path: str, db_mtime: float) -> pd.DataFrame:
    _ = db_mtime
    query = """
        SELECT id, company_name, title, location_raw, location_normalized, is_apac,
               ats_type, ats_board_token,
               recency_status, fetch_status, is_current, matched_location_keywords,
               ats_published_at, ats_updated_at,
               ats_date_normalized, ats_date_source, ats_age_days, ats_age_bucket,
               first_seen_at, last_seen_at,
               jd_text_length, normalized_url, url, jd_text
        FROM jobs
        ORDER BY last_seen_at DESC, company_name, title
    """
    return read_sql(db_path, query)


@st.cache_data(show_spinner=False)
def load_companies(db_path: str, db_mtime: float) -> pd.DataFrame:
    _ = db_mtime
    query = """
        SELECT id, company_name_guess, ats_type, ats_token, api_status, api_error,
               total_open_jobs, china_keyword_hits, recent_china_keyword_hits,
               sample_url, discovered_keyword, source_query, discovered_at,
               last_checked_at
        FROM discovered_companies
        ORDER BY recent_china_keyword_hits DESC, china_keyword_hits DESC,
                 company_name_guess, ats_type, ats_token
    """
    return read_sql(db_path, query)


@st.cache_data(show_spinner=False)
def load_candidates(db_path: str, db_mtime: float) -> pd.DataFrame:
    _ = db_mtime
    query = """
        SELECT id, status, source, source_query, result_title, result_url,
               discovered_keyword, ats_type, ats_token, company_name_guess,
               url_kind, discovered_at, reviewed_at, notes
        FROM discovery_candidates
        ORDER BY discovered_at DESC, source_query, result_url
    """
    return read_sql(db_path, query)


def read_sql(db_path: str, query: str) -> pd.DataFrame:
    read_only_uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    with sqlite3.connect(read_only_uri, uri=True, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        return pd.read_sql_query(query, conn).fillna("")


def show_summary(
    jobs_df: pd.DataFrame, companies_df: pd.DataFrame, candidates_df: pd.DataFrame
) -> None:
    current_jobs = int((jobs_df["is_current"] == 1).sum()) if not jobs_df.empty else 0
    keyword_jobs = int(
        (
            (jobs_df["is_current"] == 1)
            & (jobs_df["matched_location_keywords"].astype(str).str.len() > 0)
        ).sum()
    ) if not jobs_df.empty else 0
    recent_keyword_jobs = int(
        (
            (jobs_df["is_current"] == 1)
            & (jobs_df["matched_location_keywords"].astype(str).str.len() > 0)
            & (
                jobs_df["recency_status"].isin(
                    ["recent_published", "recent_updated", "newly_seen"]
                )
            )
        ).sum()
    ) if not jobs_df.empty else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("全部岗位", f"{len(jobs_df):,}")
    col2.metric("当前有效", f"{current_jobs:,}")
    col3.metric("关键词命中", f"{keyword_jobs:,}")
    col4.metric("近期命中", f"{recent_keyword_jobs:,}")
    col5.metric("公司", f"{len(companies_df):,}")

    if not candidates_df.empty:
        st.caption(f"候选 URL: {len(candidates_df):,} 条")


def render_jobs_tab(jobs_df: pd.DataFrame) -> None:
    if jobs_df.empty:
        st.info("jobs 表暂无数据。先运行 `python main.py` 抓取岗位。")
        return

    st.subheader("岗位筛选")
    filtered_df = filter_jobs(jobs_df)

    left, right = st.columns([0.72, 0.28], gap="large")
    with left:
        render_jobs_table(filtered_df)
    with right:
        render_job_detail(filtered_df)


def filter_jobs(jobs_df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("岗位筛选")
        only_current = st.checkbox("只看当前有效岗位", value=True)
        only_keyword = st.checkbox("只看 China/APAC 关键词命中", value=True)
        recent_only = st.checkbox("只看近期岗位", value=False)
        apac_only = st.checkbox("只看 APAC 岗位", value=False)

        search_text = st.text_input(
            "全文搜索",
            placeholder="公司、标题、地点、关键词、JD...",
        ).strip()

        ats_options = sorted(jobs_df["ats_type"].dropna().astype(str).unique())
        ats_filter = st.multiselect("ATS 类型", ats_options)

        recency_options = sorted(
            jobs_df["recency_status"].dropna().astype(str).unique()
        )
        recency_filter = st.multiselect("Recency", recency_options)

        fetch_options = sorted(jobs_df["fetch_status"].dropna().astype(str).unique())
        fetch_filter = st.multiselect("Fetch status", fetch_options)

        available_buckets = set(jobs_df["ats_age_bucket"].dropna().astype(str))
        bucket_order = [
            "0-7 days",
            "8-14 days",
            "15-30 days",
            "31-60 days",
            "60+ days",
            "unknown",
        ]
        age_bucket_options = [
            bucket for bucket in bucket_order if bucket in available_buckets
        ]
        age_bucket_filter = st.multiselect(
            "ATS 发布时间范围",
            age_bucket_options,
            default=[
                bucket
                for bucket in ["0-7 days", "8-14 days", "15-30 days"]
                if bucket in age_bucket_options
            ],
        )

        company_options = sorted(
            jobs_df["company_name"].dropna().astype(str).unique()
        )
        company_filter = st.multiselect("公司", company_options)

        title_filter = st.text_input(
            "岗位名称搜索",
            placeholder="输入岗位名称关键词...",
        ).strip()


        location_counts = (
            jobs_df["location_normalized"]
            .astype(str)
            .replace("", pd.NA)
            .dropna()
            .value_counts()
        )
        location_options = location_counts.index.tolist()
        location_filter = st.multiselect(
            "地点 / Location",
            location_options,
            format_func=lambda location: f"{location} ({location_counts[location]:,})",
        )

        max_rows = st.number_input(
            "表格最多显示行数",
            min_value=50,
            max_value=5000,
            value=1000,
            step=50,
        )

    df = jobs_df.copy()
    if only_current:
        df = df[df["is_current"] == 1]
    if only_keyword:
        df = df[df["matched_location_keywords"].astype(str).str.len() > 0]
    if recent_only:
        df = df[
            df["recency_status"].isin(
                ["recent_published", "recent_updated", "newly_seen"]
            )
        ]
    if apac_only:
        df = df[df["is_apac"] == 1]
    if ats_filter:
        df = df[df["ats_type"].isin(ats_filter)]
    if recency_filter:
        df = df[df["recency_status"].isin(recency_filter)]
    if fetch_filter:
        df = df[df["fetch_status"].isin(fetch_filter)]
    if age_bucket_filter:
        df = df[df["ats_age_bucket"].astype(str).isin(age_bucket_filter)]
    if company_filter:
        df = df[df["company_name"].isin(company_filter)]
    if title_filter:
        df = df[
            df["title"].astype(str).str.contains(
                title_filter, case=False, na=False, regex=False
            )
        ]
    if location_filter:
        df = df[df["location_normalized"].isin(location_filter)]
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

    df = df.sort_values(
        by=["last_seen_at", "company_name", "title"],
        ascending=[False, True, True],
    )
    st.session_state["jobs_display_limit"] = int(max_rows)
    return df


def render_jobs_table(filtered_df: pd.DataFrame) -> None:
    limit = st.session_state.get("jobs_display_limit", 1000)
    st.write(f"筛选结果: **{len(filtered_df):,}** 条")

    display_columns = [
        "company_name",
        "title",
        "location_raw",
        "location_normalized",
        "is_apac",
        "recency_status",
        "matched_location_keywords",
        "ats_type",
        "fetch_status",
        "ats_published_at",
        "ats_date_normalized",
        "ats_age_days",
        "ats_age_bucket",
        "first_seen_at",
        "normalized_url",
    ]
    display_df = filtered_df.head(limit).loc[:, display_columns].rename(
        columns={
            "company_name": "公司",
            "title": "岗位名称",
            "location_raw": "地点",
            "location_normalized": "标准地点",
            "is_apac": "APAC",
            "recency_status": "新鲜度",
            "matched_location_keywords": "命中关键词",
            "ats_type": "ATS",
            "fetch_status": "抓取状态",
            "ats_published_at": "发布时间",
            "ats_date_normalized": "ATS日期",
            "ats_age_days": "ATS天数",
            "ats_age_bucket": "ATS范围",
            "first_seen_at": "首次发现",
            "normalized_url": "链接",
        }
    )

    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        height=620,
        column_config={
            "链接": st.column_config.LinkColumn("链接", display_text="打开"),
        },
    )

    csv = filtered_df.loc[:, JOB_COLUMNS].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "下载当前筛选结果 CSV",
        data=csv,
        file_name="filtered_jobs.csv",
        mime="text/csv",
    )


def render_job_detail(filtered_df: pd.DataFrame) -> None:
    st.subheader("岗位详情")
    if filtered_df.empty:
        st.info("没有符合当前筛选条件的岗位。")
        return

    detail_df = filtered_df.head(st.session_state.get("jobs_display_limit", 1000))
    labels = {
        make_job_label(row): int(row["id"])
        for _, row in detail_df.iterrows()
    }
    selected_label = st.selectbox("选择一条岗位查看详情", list(labels.keys()))
    selected_id = labels[selected_label]
    row = detail_df[detail_df["id"] == selected_id].iloc[0]

    st.markdown(f"**岗位名称：{row['title']}**")
    st.write(row["company_name"] or "Unknown company")
    st.write(row["location_normalized"] or row["location_raw"] or "Unknown location")

    url = row["normalized_url"] or row["url"]
    if url:
        st.link_button("打开岗位链接", url)

    st.text_input("Recency", value=str(row["recency_status"]), disabled=True)
    st.text_input("命中关键词", value=str(row["matched_location_keywords"]), disabled=True)
    st.text_input("发布时间", value=str(row["ats_published_at"]), disabled=True)
    st.text_input("更新时间", value=str(row["ats_updated_at"]), disabled=True)
    st.text_input("ATS日期", value=str(row["ats_date_normalized"]), disabled=True)
    st.text_input("ATS日期来源", value=str(row["ats_date_source"]), disabled=True)
    st.text_input("ATS年龄范围", value=str(row["ats_age_bucket"]), disabled=True)
    st.text_input("首次发现", value=str(row["first_seen_at"]), disabled=True)

    jd_text = str(row["jd_text"] or "")
    st.text_area("JD 文本", value=jd_text, height=360, disabled=True)


def make_job_label(row: pd.Series) -> str:
    company = str(row.get("company_name") or "Unknown")
    title = str(row.get("title") or "Untitled")
    location = str(row.get("location_raw") or "")
    job_id = row.get("id")
    label = f"{company} | {title}"
    if location:
        label += f" | {location}"
    return f"{label} | #{job_id}"


def render_companies_tab(companies_df: pd.DataFrame) -> None:
    st.subheader("公司汇总")
    if companies_df.empty:
        st.info("discovered_companies 表暂无数据。")
        return

    status_options = sorted(companies_df["api_status"].astype(str).unique())
    selected_status = st.multiselect("API 状态", status_options)
    only_hits = st.checkbox("只看有 China/APAC 命中岗位的公司", value=True)

    df = companies_df.copy()
    if selected_status:
        df = df[df["api_status"].isin(selected_status)]
    if only_hits:
        df = df[df["china_keyword_hits"].fillna(0).astype(int) > 0]

    st.write(f"筛选结果: **{len(df):,}** 家公司")
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
    st.dataframe(
        df.loc[:, display_columns].rename(
            columns={
                "company_name_guess": "公司",
                "ats_type": "ATS",
                "ats_token": "Token",
                "api_status": "API 状态",
                "total_open_jobs": "开放岗位",
                "china_keyword_hits": "关键词命中",
                "recent_china_keyword_hits": "近期命中",
                "last_checked_at": "最近检查",
                "sample_url": "样例 URL",
            }
        ),
        width="stretch",
        hide_index=True,
        height=620,
        column_config={
            "样例 URL": st.column_config.LinkColumn("样例 URL", display_text="打开"),
        },
    )


def render_candidates_tab(candidates_df: pd.DataFrame) -> None:
    st.subheader("候选 URL")
    if candidates_df.empty:
        st.info("discovery_candidates 表暂无数据。")
        return

    status_options = sorted(candidates_df["status"].astype(str).unique())
    selected_status = st.multiselect("审核状态", status_options, default=[])
    search_text = st.text_input("候选 URL 搜索", placeholder="公司、URL、query...")

    df = candidates_df.copy()
    if selected_status:
        df = df[df["status"].isin(selected_status)]
    if search_text:
        mask = pd.Series(False, index=df.index)
        for column in ["company_name_guess", "result_url", "source_query", "notes"]:
            mask |= df[column].astype(str).str.contains(
                search_text, case=False, na=False, regex=False
            )
        df = df[mask]

    st.write(f"筛选结果: **{len(df):,}** 条")
    display_columns = [
        "status",
        "company_name_guess",
        "ats_type",
        "ats_token",
        "url_kind",
        "source_query",
        "result_title",
        "result_url",
        "discovered_keyword",
        "discovered_at",
        "notes",
    ]
    st.dataframe(
        df.loc[:, display_columns].rename(
            columns={
                "status": "状态",
                "company_name_guess": "公司",
                "ats_type": "ATS",
                "ats_token": "Token",
                "url_kind": "URL 类型",
                "source_query": "搜索 Query",
                "result_title": "标题",
                "result_url": "URL",
                "discovered_keyword": "关键词",
                "discovered_at": "发现时间",
                "notes": "备注",
            }
        ),
        width="stretch",
        hide_index=True,
        height=620,
        column_config={
            "URL": st.column_config.LinkColumn("URL", display_text="打开"),
        },
    )


if __name__ == "__main__":
    main()
