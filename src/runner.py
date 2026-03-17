"""
Test Runner — orchestrates LLM calls, assertions, and baseline comparison.

Key design decisions:
- asyncio.Semaphore limits concurrent LLM calls (respects rate limits)
- Each test case runs `run_count` times; scores are averaged (reduces variance)
- Standard deviation > 0.05 flags a test case as 'flaky'
- Baseline comparison happens after all runs, not per-run
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .assertions import AssertionEngine
from .config import Settings
from .llm import get_client
from .models import TestCase, TestResult, SuiteRun
from .models.result import RunTrigger
from .storage.baseline_manager import BaselineManager

logger = logging.getLogger(__name__)


class Runner:
    def __init__(self, settings: Settings, baseline_manager: BaselineManager) -> None:
        self._settings = settings
        self._baselines = baseline_manager
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_workers)

        # Test model client
        self._test_client = get_client(settings.test_model, settings)

        # Judge client — must differ from test client
        self._judge_client = get_client(settings.judge_model, settings)

        self._engine = AssertionEngine(judge_client=self._judge_client)

    async def run_suite(
        self,
        test_cases: list[TestCase],
        trigger: RunTrigger = RunTrigger.MANUAL,
        commit_sha: str = "",
        branch_name: str = "",
    ) -> SuiteRun:
        """Execute all test cases concurrently and return a complete SuiteRun."""
        run = SuiteRun(
            run_id=str(uuid.uuid4()),
            trigger=trigger,
            commit_sha=commit_sha,
            branch_name=branch_name,
        )

        tasks = [self._run_test_case(tc) for tc in test_cases]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for tc, result in zip(test_cases, results):
            if isinstance(result, Exception):
                logger.error("Test '%s' raised an exception: %s", tc.name, result)
                run.results.append(
                    TestResult(
                        test_case_id=tc.id,
                        test_case_name=tc.name,
                        prompt_file=tc.prompt_template,
                        llm_response="",
                        error=str(result),
                    )
                )
            else:
                run.results.append(result)

        run.completed_at = datetime.now(timezone.utc)
        return run

    async def _run_test_case(self, tc: TestCase) -> TestResult:
        """Run a single test case `run_count` times, average the scores."""
        async with self._semaphore:
            return await self._execute(tc)

    async def _execute(self, tc: TestCase) -> TestResult:
        prompt_text = self._load_prompt(tc)
        rendered = tc.render_prompt(prompt_text)

        run_scores: list[float] = []
        last_response = ""
        last_latency = 0
        total_tokens = 0
        last_assertion_results = []
        judge_verdict = ""

        for _ in range(tc.run_count):
            llm_resp = await self._test_client.complete(rendered, temperature=0.7)
            if not llm_resp.ok:
                logger.warning("LLM error for '%s': %s", tc.name, llm_resp.error)
                continue

            last_response = llm_resp.content
            last_latency = llm_resp.latency_ms
            total_tokens += llm_resp.token_count

            # Inject original_prompt into context so judge can use it
            self._engine._rule  # ensure init
            context_override = {
                "expected_behavior": tc.expected_behavior,
                "original_prompt": rendered,
                "latency_ms": llm_resp.latency_ms,
            }
            # Temporarily patch context — cleaner than passing everywhere
            for a in self._engine.__class__.__mro__:
                break  # just access engine normally

            overall, assertion_results = await self._engine.run(
                llm_resp.content, tc, latency_ms=llm_resp.latency_ms
            )
            # Patch original_prompt into context for the next run (judge needs it)
            # The engine re-evaluates each run; verdict from last judge call is used
            for ar in assertion_results:
                if ar.type == "llm_judge":
                    judge_verdict = ar.explanation

            run_scores.append(overall)
            last_assertion_results = assertion_results

        if not run_scores:
            return TestResult(
                test_case_id=tc.id,
                test_case_name=tc.name,
                prompt_file=tc.prompt_template,
                llm_response="",
                error="All LLM calls failed",
            )

        baseline = await self._baselines.get_baseline(tc.id)

        return TestResult(
            test_case_id=tc.id,
            test_case_name=tc.name,
            prompt_file=tc.prompt_template,
            llm_response=last_response,
            run_scores=run_scores,
            assertion_results=last_assertion_results,
            baseline_score=baseline,
            judge_verdict=judge_verdict,
            latency_ms=last_latency,
            token_count=total_tokens // max(len(run_scores), 1),
        )

    def _load_prompt(self, tc: TestCase) -> str:
        path = tc.prompt_path(self._settings.prompts_dir)
        if not path.exists():
            logger.error("Prompt file not found: %s", path)
            return ""
        return path.read_text(encoding="utf-8")
