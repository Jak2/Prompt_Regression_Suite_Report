"""
Streamlit Dashboard — four views for monitoring prompt health over time.

Views:
  1. Health Overview    — headline metrics + 30-day heatmap
  2. Regression History — time-ordered feed, expandable details
  3. Score Trends       — per-test trend chart with 7-day rolling average
  4. Model Comparison   — side-by-side scoring across models (from DB)

Design: The dashboard reads directly from the SQLite/PostgreSQL database.
It does NOT call the FastAPI layer — direct DB access is faster and avoids
the dependency on the API server being running.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── bootstrap path so we can import from src ──────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.storage.database import init_db, get_engine, get_session_factory
from src.storage.baseline_manager import BaselineManager
from src.storage.orm_models import TestCaseORM, TestResultORM, TestRunORM
from sqlalchemy import select, func


# ── App config ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Prompt Regression Suite",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

_SETTINGS = get_settings()


# ── DB helpers (sync wrappers for Streamlit's synchronous context) ─────────────

def _run_async(coro):
    """Run an async coroutine from synchronous Streamlit code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
    except RuntimeError:
        pass
    return asyncio.run(coro)


@st.cache_resource
def _get_factory():
    _run_async(init_db(_SETTINGS.database_url))
    engine = get_engine(_SETTINGS.database_url)
    return get_session_factory(engine)


@st.cache_data(ttl=30)
def fetch_runs(limit: int = 200) -> pd.DataFrame:
    async def _q():
        async with _get_factory()() as s:
            rows = await s.execute(
                select(TestRunORM).order_by(TestRunORM.run_started_at.desc()).limit(limit)
            )
            return [
                {
                    "run_id": r.id,
                    "trigger": r.trigger,
                    "branch": r.branch_name,
                    "commit": r.commit_sha[:8] if r.commit_sha else "",
                    "started_at": r.run_started_at,
                    "total": r.total_tests,
                    "passed": r.passed_count,
                    "regressions": r.regression_count,
                    "pass_rate": round(r.passed_count / r.total_tests, 2) if r.total_tests else 0,
                }
                for r in rows.scalars()
            ]
    data = _run_async(_q())
    return pd.DataFrame(data) if data else pd.DataFrame()


@st.cache_data(ttl=30)
def fetch_results(limit: int = 2000) -> pd.DataFrame:
    async def _q():
        async with _get_factory()() as s:
            rows = await s.execute(
                select(TestResultORM, TestCaseORM)
                .join(TestCaseORM, TestResultORM.test_case_id == TestCaseORM.id)
                .order_by(TestResultORM.recorded_at.desc())
                .limit(limit)
            )
            return [
                {
                    "test_case_id": res.test_case_id,
                    "test_case_name": tc.name,
                    "prompt_file": tc.prompt_file_path,
                    "tags": tc.tags,
                    "recorded_at": res.recorded_at,
                    "overall_score": res.overall_score,
                    "regression": res.regression_detected,
                    "score_delta": res.score_delta,
                    "latency_ms": res.latency_ms,
                    "run_id": res.test_run_id,
                    "judge_verdict": res.judge_verdict,
                    "llm_response": res.llm_response,
                    "std_dev": res.std_dev,
                    "error": res.error,
                }
                for res, tc in rows
            ]
    data = _run_async(_q())
    return pd.DataFrame(data) if data else pd.DataFrame()


@st.cache_data(ttl=30)
def fetch_baselines() -> pd.DataFrame:
    async def _q():
        from src.storage.orm_models import BaselineORM
        async with _get_factory()() as s:
            rows = await s.execute(select(BaselineORM))
            return [
                {
                    "test_case_id": r.test_case_id,
                    "score": r.score,
                    "set_at": r.set_at,
                    "commit": r.set_by_commit[:8] if r.set_by_commit else "",
                    "reason": r.reason,
                }
                for r in rows.scalars()
            ]
    data = _run_async(_q())
    return pd.DataFrame(data) if data else pd.DataFrame()


# ── Sidebar ────────────────────────────────────────────────────────────────────

st.sidebar.title("🧪 Prompt Regression Suite")
view = st.sidebar.radio(
    "View",
    ["Health Overview", "Regression History", "Score Trends", "Model Comparison", "Baselines"],
)
st.sidebar.divider()
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()


# ── View 1: Health Overview ────────────────────────────────────────────────────

if view == "Health Overview":
    st.title("Health Overview")

    runs_df = fetch_runs()
    results_df = fetch_results()

    if runs_df.empty:
        st.info("No test runs found. Run `prs run` to get started.")
        st.stop()

    last_run = runs_df.iloc[0]
    recent = results_df[results_df["run_id"] == last_run["run_id"]] if not results_df.empty else pd.DataFrame()

    # ── Headline metrics ──
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Suite Pass Rate",
        f"{last_run['pass_rate']:.0%}",
        help="Passed / total in the latest run",
    )
    c2.metric(
        "Regressions (latest run)",
        int(last_run["regressions"]),
        delta=None,
    )
    c3.metric(
        "Avg LLM Judge Score (7d)",
        f"{results_df['overall_score'].mean():.3f}" if not results_df.empty else "—",
    )
    c4.metric(
        "Avg Latency (latest)",
        f"{recent['latency_ms'].mean():.0f}ms" if not recent.empty else "—",
    )

    st.divider()

    # ── 30-day heatmap ──
    if not results_df.empty:
        st.subheader("30-Day Pass/Fail Heatmap")
        results_df["date"] = pd.to_datetime(results_df["recorded_at"]).dt.date
        heat = (
            results_df.groupby(["test_case_name", "date"])["regression"]
            .max()
            .reset_index()
        )
        heat["value"] = heat["regression"].astype(int)
        pivot = heat.pivot(index="test_case_name", columns="date", values="value").fillna(-1)
        fig = px.imshow(
            pivot,
            color_continuous_scale=["#e8f5e9", "#ffcdd2"],
            labels={"color": "Regression"},
            aspect="auto",
            title="Red = regression detected on that day",
        )
        fig.update_layout(height=max(300, len(pivot) * 22 + 80))
        st.plotly_chart(fig, use_container_width=True)

    # ── Recent runs table ──
    st.subheader("Recent Runs")
    st.dataframe(
        runs_df[["started_at", "trigger", "branch", "commit", "total", "passed", "regressions"]].head(20),
        use_container_width=True,
    )


# ── View 2: Regression History ────────────────────────────────────────────────

elif view == "Regression History":
    st.title("Regression History")

    results_df = fetch_results()
    if results_df.empty:
        st.info("No results yet.")
        st.stop()

    regressions = results_df[results_df["regression"]].copy()
    if regressions.empty:
        st.success("No regressions detected across all runs. 🎉")
        st.stop()

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        prompt_filter = st.multiselect(
            "Filter by prompt file",
            options=sorted(regressions["prompt_file"].unique()),
        )
    with col2:
        date_range = st.date_input("Date range", value=[], help="Leave empty for all dates")

    if prompt_filter:
        regressions = regressions[regressions["prompt_file"].isin(prompt_filter)]
    if len(date_range) == 2:
        regressions["date"] = pd.to_datetime(regressions["recorded_at"]).dt.date
        regressions = regressions[
            (regressions["date"] >= date_range[0]) & (regressions["date"] <= date_range[1])
        ]

    st.write(f"**{len(regressions)} regression event(s)**")

    for _, row in regressions.head(50).iterrows():
        with st.expander(
            f"🔴 {row['test_case_name']} — delta {row['score_delta']:+.3f} — "
            f"{str(row['recorded_at'])[:16]}"
        ):
            c1, c2, c3 = st.columns(3)
            c1.metric("Score", f"{row['overall_score']:.3f}")
            c2.metric("Delta", f"{row['score_delta']:+.3f}")
            c3.metric("Latency", f"{row['latency_ms']}ms")
            st.caption(f"**Prompt file:** {row['prompt_file']}")
            st.caption(f"**Judge verdict:** {row['judge_verdict']}")
            if row["llm_response"]:
                st.text_area("LLM Response", row["llm_response"], height=120, key=str(_))


# ── View 3: Score Trends ───────────────────────────────────────────────────────

elif view == "Score Trends":
    st.title("Score Trends")

    results_df = fetch_results()
    baselines_df = fetch_baselines()

    if results_df.empty:
        st.info("No results yet.")
        st.stop()

    test_names = sorted(results_df["test_case_name"].unique())
    selected = st.selectbox("Select test case", test_names)

    tc_data = results_df[results_df["test_case_name"] == selected].copy()
    tc_data = tc_data.sort_values("recorded_at")
    tc_data["recorded_at"] = pd.to_datetime(tc_data["recorded_at"])
    tc_data["rolling_avg"] = tc_data["overall_score"].rolling(7, min_periods=1).mean()

    baseline_val = None
    if not baselines_df.empty:
        tc_id = tc_data["test_case_id"].iloc[0] if not tc_data.empty else None
        bl_row = baselines_df[baselines_df["test_case_id"] == tc_id]
        baseline_val = bl_row["score"].iloc[0] if not bl_row.empty else None

    fig = go.Figure()
    # Raw scores (faint dots)
    fig.add_trace(go.Scatter(
        x=tc_data["recorded_at"],
        y=tc_data["overall_score"],
        mode="markers",
        name="Raw score",
        marker=dict(size=5, color="lightblue", opacity=0.5),
    ))
    # 7-day rolling average
    fig.add_trace(go.Scatter(
        x=tc_data["recorded_at"],
        y=tc_data["rolling_avg"],
        mode="lines",
        name="7-day rolling avg",
        line=dict(color="steelblue", width=2),
    ))
    # Baseline horizontal line
    if baseline_val is not None:
        fig.add_hline(
            y=baseline_val,
            line_dash="dash",
            line_color="orange",
            annotation_text=f"Baseline {baseline_val:.3f}",
        )
    # Regression events (red dots)
    regressions = tc_data[tc_data["regression"]]
    if not regressions.empty:
        fig.add_trace(go.Scatter(
            x=regressions["recorded_at"],
            y=regressions["overall_score"],
            mode="markers",
            name="Regression",
            marker=dict(size=10, color="red", symbol="x"),
        ))

    fig.update_layout(
        title=f"Score Trend: {selected}",
        xaxis_title="Date",
        yaxis_title="Score",
        yaxis=dict(range=[0, 1.05]),
        height=450,
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Mean score", f"{tc_data['overall_score'].mean():.3f}")
    col2.metric("Std dev", f"{tc_data['overall_score'].std():.3f}")
    col3.metric("Regression events", int(tc_data["regression"].sum()))


# ── View 4: Model Comparison ──────────────────────────────────────────────────

elif view == "Model Comparison":
    st.title("Model Comparison")
    st.info(
        "This view compares multiple models on the same test cases. "
        "Run `prs run` with different TEST_MODEL settings to populate data."
    )

    results_df = fetch_results()
    if results_df.empty:
        st.stop()

    st.subheader("Score Distribution by Prompt File")
    fig = px.box(
        results_df,
        x="prompt_file",
        y="overall_score",
        color="prompt_file",
        points="all",
        title="Score distribution per prompt",
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Score")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Score vs Latency")
    fig2 = px.scatter(
        results_df,
        x="latency_ms",
        y="overall_score",
        color="prompt_file",
        hover_data=["test_case_name"],
        title="Score vs Latency (lower-right is best)",
    )
    st.plotly_chart(fig2, use_container_width=True)


# ── View 5: Baselines ─────────────────────────────────────────────────────────

elif view == "Baselines":
    st.title("Baseline Management")

    baselines_df = fetch_baselines()
    if baselines_df.empty:
        st.info("No baselines set. Run `prs run --update-baselines` after your first run.")
        st.stop()

    st.dataframe(baselines_df, use_container_width=True)

    st.divider()
    st.subheader("Force Reset a Baseline")
    st.warning(
        "Only use this when intentionally accepting a behaviour change. "
        "A documented reason is required and creates an audit trail."
    )

    with st.form("reset_form"):
        tc_id = st.text_input("Test Case ID")
        new_score = st.number_input("New Score", min_value=0.0, max_value=1.0, step=0.01)
        reason = st.text_input("Reason (required)")
        submitted = st.form_submit_button("Reset Baseline")

    if submitted:
        if not reason.strip():
            st.error("A reason is required.")
        else:
            from src.storage.baseline_manager import BaselineManager
            manager = BaselineManager(_get_factory())
            _run_async(manager.force_reset(tc_id, new_score, reason))
            st.success(f"Baseline for '{tc_id}' reset to {new_score:.3f}")
            st.cache_data.clear()
