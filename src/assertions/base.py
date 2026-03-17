"""Abstract base for all assertion types."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.result import AssertionResult
from ..models.test_case import AssertionConfig


class Assertion(ABC):
    """Every assertion receives a config and produces a scored result."""

    @abstractmethod
    async def evaluate(
        self,
        response: str,
        config: AssertionConfig,
        context: dict,
    ) -> AssertionResult:
        """
        Args:
            response: The raw LLM output being tested.
            config: The assertion parameters from the YAML.
            context: Extra data — original_prompt, expected_behavior, retrieved_context.
        Returns:
            AssertionResult with score in [0, 1].
        """
        ...
