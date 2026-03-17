"""
Baseline Manager — the three-rule update policy implemented correctly.

Rule 1: Baselines update automatically on every merge to main.
Rule 2: Baselines NEVER update on PR runs (comparison-only).
Rule 3: Forced reset requires a documented reason (creates audit trail).

Why this matters: if baselines updated on every run, regressions would
be immediately forgotten. If they never updated, every improvement would
be flagged as a regression. The three-rule policy is the minimum viable
solution that makes the system both sensitive and trustworthy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .orm_models import BaselineORM, TestCaseORM, TestResultORM, TestRunORM
from ..models import TestCase, TestResult, SuiteRun

logger = logging.getLogger(__name__)


class BaselineManager:
    def __init__(self, session_factory) -> None:  # type: ignore[annotation-unchecked]
        self._factory = session_factory

    async def get_baseline(self, test_case_id: str) -> float:
        """Return the current baseline score for a test case (0.0 if none set)."""
        async with self._factory() as session:
            row = await session.scalar(
                select(BaselineORM).where(BaselineORM.test_case_id == test_case_id)
            )
            return row.score if row else 0.0

    async def update_baselines_from_run(
        self,
        suite_run: SuiteRun,
        commit_sha: str = "",
    ) -> None:
        """
        Rule 1: Call this ONLY when merging to main.
        Updates baselines from the current run's scores.
        """
        async with self._factory() as session:
            for result in suite_run.results:
                if result.error:
                    continue
                await self._upsert_baseline(
                    session,
                    result.test_case_id,
                    result.overall_score,
                    commit_sha,
                    reason="Automatic update on main merge",
                )
            await session.commit()
        logger.info("Updated %d baselines from run %s", len(suite_run.results), suite_run.run_id)

    async def force_reset(
        self,
        test_case_id: str,
        new_score: float,
        reason: str,
        commit_sha: str = "",
    ) -> None:
        """
        Rule 3: Intentional baseline reset with mandatory documented reason.
        Creates a full audit trail via the reason field.
        """
        if not reason.strip():
            raise ValueError("A non-empty reason is required for a forced baseline reset.")
        async with self._factory() as session:
            await self._upsert_baseline(session, test_case_id, new_score, commit_sha, reason)
            await session.commit()
        logger.info(
            "Forced baseline reset for '%s' to %.3f. Reason: %s",
            test_case_id, new_score, reason,
        )

    async def save_run(self, suite_run: SuiteRun, test_cases: list[TestCase]) -> None:
        """Persist a SuiteRun and all its results to the database."""
        async with self._factory() as session:
            # Ensure all test cases exist in the registry table
            for tc in test_cases:
                existing = await session.get(TestCaseORM, tc.id)
                if not existing:
                    session.add(TestCaseORM(
                        id=tc.id,
                        name=tc.name,
                        prompt_file_path=tc.prompt_template,
                        expected_behavior=tc.expected_behavior,
                        assertions=[a.model_dump() for a in tc.assertions],
                        tags=tc.tags,
                        file_path=tc.file_path,
                    ))

            # Persist the run header
            run_orm = TestRunORM(
                id=suite_run.run_id,
                trigger=suite_run.trigger.value,
                commit_sha=suite_run.commit_sha,
                branch_name=suite_run.branch_name,
                run_started_at=suite_run.started_at,
                run_completed_at=suite_run.completed_at,
                total_tests=suite_run.total_tests,
                passed_count=suite_run.passed_count,
                regression_count=suite_run.regression_count,
            )
            session.add(run_orm)

            # Persist each result
            for r in suite_run.results:
                session.add(TestResultORM(
                    test_run_id=suite_run.run_id,
                    test_case_id=r.test_case_id,
                    llm_response=r.llm_response,
                    overall_score=r.overall_score,
                    assertion_scores={
                        ar.type: {"score": ar.score, "passed": ar.passed, "explanation": ar.explanation}
                        for ar in r.assertion_results
                    },
                    regression_detected=r.regression_detected,
                    score_delta=r.score_delta,
                    judge_verdict=r.judge_verdict,
                    latency_ms=r.latency_ms,
                    token_count=r.token_count,
                    run_scores=r.run_scores,
                    std_dev=r.std_dev,
                    error=r.error,
                ))

            await session.commit()

    async def get_score_history(
        self,
        test_case_id: str,
        limit: int = 90,
    ) -> list[dict]:
        """Fetch recent score history for dashboard trend charts."""
        async with self._factory() as session:
            rows = await session.execute(
                select(TestResultORM)
                .where(TestResultORM.test_case_id == test_case_id)
                .order_by(TestResultORM.recorded_at.desc())
                .limit(limit)
            )
            return [
                {
                    "recorded_at": r.recorded_at.isoformat(),
                    "overall_score": r.overall_score,
                    "regression_detected": r.regression_detected,
                    "score_delta": r.score_delta,
                    "latency_ms": r.latency_ms,
                }
                for r in rows.scalars()
            ]

    async def get_recent_regressions(self, limit: int = 50) -> list[dict]:
        """All regression events ordered by most recent first — for the dashboard feed."""
        async with self._factory() as session:
            rows = await session.execute(
                select(TestResultORM, TestCaseORM, TestRunORM)
                .join(TestCaseORM, TestResultORM.test_case_id == TestCaseORM.id)
                .join(TestRunORM, TestResultORM.test_run_id == TestRunORM.id)
                .where(TestResultORM.regression_detected == True)  # noqa: E712
                .order_by(TestResultORM.recorded_at.desc())
                .limit(limit)
            )
            return [
                {
                    "recorded_at": result.recorded_at.isoformat(),
                    "test_case_name": tc.name,
                    "prompt_file": tc.prompt_file_path,
                    "score_delta": result.score_delta,
                    "overall_score": result.overall_score,
                    "judge_verdict": result.judge_verdict,
                    "commit_sha": run.commit_sha,
                    "branch_name": run.branch_name,
                    "llm_response": result.llm_response,
                }
                for result, tc, run in rows
            ]

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _upsert_baseline(
        self,
        session: AsyncSession,
        test_case_id: str,
        score: float,
        commit_sha: str,
        reason: str,
    ) -> None:
        existing = await session.scalar(
            select(BaselineORM).where(BaselineORM.test_case_id == test_case_id)
        )
        if existing:
            existing.score = score
            existing.set_at = datetime.now(timezone.utc)
            existing.set_by_commit = commit_sha
            existing.reason = reason
        else:
            session.add(BaselineORM(
                test_case_id=test_case_id,
                score=score,
                set_by_commit=commit_sha,
                reason=reason,
            ))
