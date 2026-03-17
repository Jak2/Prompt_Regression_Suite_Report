from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ...config import get_settings
from ...storage.orm_models import TestRunORM, TestResultORM

router = APIRouter()


def _get_session():
    s = get_settings()
    from ...storage.database import get_engine, get_session_factory
    engine = get_engine(s.database_url)
    return get_session_factory(engine)


@router.get("/")
async def list_runs(limit: int = 50) -> list[dict]:
    factory = _get_session()
    async with factory() as session:
        rows = await session.execute(
            select(TestRunORM).order_by(TestRunORM.run_started_at.desc()).limit(limit)
        )
        return [
            {
                "id": r.id,
                "trigger": r.trigger,
                "commit_sha": r.commit_sha,
                "branch_name": r.branch_name,
                "started_at": r.run_started_at.isoformat() if r.run_started_at else None,
                "completed_at": r.run_completed_at.isoformat() if r.run_completed_at else None,
                "total_tests": r.total_tests,
                "passed_count": r.passed_count,
                "regression_count": r.regression_count,
            }
            for r in rows.scalars()
        ]


@router.get("/{run_id}/results")
async def get_run_results(run_id: str) -> list[dict]:
    factory = _get_session()
    async with factory() as session:
        run = await session.get(TestRunORM, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        rows = await session.execute(
            select(TestResultORM).where(TestResultORM.test_run_id == run_id)
        )
        return [
            {
                "test_case_id": r.test_case_id,
                "overall_score": r.overall_score,
                "regression_detected": r.regression_detected,
                "score_delta": r.score_delta,
                "judge_verdict": r.judge_verdict,
                "latency_ms": r.latency_ms,
                "assertion_scores": r.assertion_scores,
                "run_scores": r.run_scores,
                "std_dev": r.std_dev,
                "error": r.error,
            }
            for r in rows.scalars()
        ]
