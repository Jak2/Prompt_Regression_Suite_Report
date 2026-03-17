"""
Pure data models for test cases — no I/O, no side effects.

Design: Pydantic v2 for zero-cost validation at parse time.
We use `model_validator` to enforce invariants (e.g. semantic_similarity requires
a reference_answer) so downstream code never needs defensive checks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AssertionConfig(BaseModel):
    """Configuration for a single assertion within a test case."""

    type: str

    # ── Semantic similarity ───────────────────────────────────────────────────
    threshold: float = 0.85
    reference_answer: str = ""

    # ── LLM judge ─────────────────────────────────────────────────────────────
    # threshold reused; judge uses expected_behavior from parent TestCase

    # ── Rule-based ────────────────────────────────────────────────────────────
    keywords: list[str] = Field(default_factory=list)
    phrases: list[str] = Field(default_factory=list)   # for not_contains
    limit: int = 0                                      # max_words / min_words
    pattern: str = ""                                   # regex_match
    expected_value: str = ""                            # starts_with / language_is
    keys: list[str] = Field(default_factory=list)       # json_contains_key
    max_seconds: float = 0.0                            # response_time_under
    reading_level_min: float = 0.0
    reading_level_max: float = 100.0

    # ── Weight for multi-assertion aggregation ────────────────────────────────
    weight: float = 1.0

    model_config = {"extra": "allow"}


class TestCase(BaseModel):
    """A single prompt regression test case parsed from a YAML file."""

    name: str
    prompt_template: str          # relative path to prompt file
    expected_behavior: str        # natural language — used as judge rubric
    assertions: list[AssertionConfig] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    run_count: int = 3            # runs averaged to reduce LLM variance
    delta_threshold: float = 0.05 # regression trigger: score drop > this
    file_path: str = ""           # set by registry after load

    @model_validator(mode="after")
    def validate_assertions(self) -> "TestCase":
        for cfg in self.assertions:
            if cfg.type == "semantic_similarity" and not cfg.reference_answer:
                raise ValueError(
                    f"Test '{self.name}': semantic_similarity requires reference_answer"
                )
        return self

    def render_prompt(self, prompt_text: str) -> str:
        """Substitute {{variable}} placeholders in the prompt text."""
        result = prompt_text
        for key, value in self.variables.items():
            result = result.replace(f"{{{{{key}}}}}", value)
        return result

    def prompt_path(self, prompts_dir: Path) -> Path:
        """Resolve the prompt template file path."""
        p = Path(self.prompt_template)
        if p.is_absolute():
            return p
        return prompts_dir / p

    @property
    def id(self) -> str:
        """Stable identifier derived from file path + name."""
        base = Path(self.file_path).stem if self.file_path else "unknown"
        return f"{base}::{self.name}"

    def model_dump_safe(self) -> dict[str, Any]:
        """Serialise to dict with Path objects coerced to strings."""
        d = self.model_dump()
        d["file_path"] = str(self.file_path)
        return d
