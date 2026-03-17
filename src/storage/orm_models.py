"""
SQLAlchemy ORM models — four tables, optimised for time-series queries.

Design: JSON columns store flexible structured data (assertion scores, tags)
without schema migrations every time we add a new assertion type.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TestCaseORM(Base):
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    expected_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    assertions: Mapped[dict] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    file_path: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    results: Mapped[list["TestResultORM"]] = relationship(
        "TestResultORM", back_populates="test_case", lazy="select"
    )
    baseline: Mapped["BaselineORM | None"] = relationship(
        "BaselineORM", back_populates="test_case", uselist=False, lazy="select"
    )


class TestRunORM(Base):
    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    branch_name: Mapped[str] = mapped_column(String(255), default="")
    run_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    run_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_tests: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    regression_count: Mapped[int] = mapped_column(Integer, default=0)

    results: Mapped[list["TestResultORM"]] = relationship(
        "TestResultORM", back_populates="run", lazy="select"
    )


class TestResultORM(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"), nullable=False)
    test_case_id: Mapped[str] = mapped_column(ForeignKey("test_cases.id"), nullable=False)
    llm_response: Mapped[str] = mapped_column(Text, default="")
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    assertion_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    regression_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    score_delta: Mapped[float] = mapped_column(Float, default=0.0)
    judge_verdict: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    run_scores: Mapped[list] = mapped_column(JSON, default=list)
    std_dev: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped["TestRunORM"] = relationship("TestRunORM", back_populates="results")
    test_case: Mapped["TestCaseORM"] = relationship("TestCaseORM", back_populates="results")


class BaselineORM(Base):
    __tablename__ = "baselines"
    __table_args__ = (UniqueConstraint("test_case_id", name="uq_baseline_test_case"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_case_id: Mapped[str] = mapped_column(
        ForeignKey("test_cases.id"), nullable=False, unique=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    set_by_commit: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(Text, default="")  # required for forced resets

    test_case: Mapped["TestCaseORM"] = relationship("TestCaseORM", back_populates="baseline")
