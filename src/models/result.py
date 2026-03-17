"""Result models — what the runner produces after executing a test case."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class RunTrigger(str, Enum):
    PULL_REQUEST = "pull_request"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class AssertionResult(BaseModel):
    type: str
    passed: bool
    score: float          # 0.0 – 1.0
    explanation: str
    weight: float = 1.0


class TestResult(BaseModel):
    test_case_id: str
    test_case_name: str
    prompt_file: str
    llm_response: str
    run_scores: list[float] = Field(default_factory=list)  # per-run scores
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    baseline_score: float = 0.0
    judge_verdict: str = ""
    latency_ms: int = 0
    token_count: int = 0
    error: Optional[str] = None

    @computed_field
    @property
    def overall_score(self) -> float:
        if not self.run_scores:
            return 0.0
        return round(statistics.mean(self.run_scores), 4)

    @computed_field
    @property
    def std_dev(self) -> float:
        if len(self.run_scores) < 2:
            return 0.0
        return round(statistics.stdev(self.run_scores), 4)

    @computed_field
    @property
    def is_flaky(self) -> bool:
        return self.std_dev > 0.05

    @computed_field
    @property
    def score_delta(self) -> float:
        return round(self.overall_score - self.baseline_score, 4)

    @computed_field
    @property
    def regression_detected(self) -> bool:
        """True when score dropped meaningfully vs baseline."""
        return self.baseline_score > 0.0 and self.score_delta < -0.05

    @computed_field
    @property
    def passed(self) -> bool:
        return not self.regression_detected and self.error is None


class SuiteRun(BaseModel):
    run_id: str
    trigger: RunTrigger = RunTrigger.MANUAL
    commit_sha: str = ""
    branch_name: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    results: list[TestResult] = Field(default_factory=list)

    @computed_field
    @property
    def total_tests(self) -> int:
        return len(self.results)

    @computed_field
    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @computed_field
    @property
    def failed_count(self) -> int:
        return self.total_tests - self.passed_count

    @computed_field
    @property
    def regression_count(self) -> int:
        return sum(1 for r in self.results if r.regression_detected)

    @computed_field
    @property
    def overall_pass_rate(self) -> float:
        if not self.total_tests:
            return 0.0
        return round(self.passed_count / self.total_tests, 4)

    @computed_field
    @property
    def has_regressions(self) -> bool:
        return self.regression_count > 0
