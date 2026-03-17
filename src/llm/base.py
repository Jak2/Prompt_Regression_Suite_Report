"""
Abstract LLM client — the only interface the rest of the codebase sees.

Design: Abstract base class forces every provider to implement the same contract.
Retry logic lives here (not in each client) to avoid duplication.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    latency_ms: int
    token_count: int
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMClient(ABC):
    """Provider-agnostic async LLM client with built-in retry + exponential back-off."""

    def __init__(
        self,
        model: str,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    async def complete(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Call the LLM with retry logic. Returns an LLMResponse always."""
        last_error: str = ""
        for attempt in range(self.max_retries):
            try:
                start = time.perf_counter()
                response = await self._call(prompt, system, temperature)
                response.latency_ms = int((time.perf_counter() - start) * 1000)
                return response
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                wait = 2 ** attempt  # exponential back-off: 1s, 2s, 4s
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s — retrying in %ds",
                    attempt + 1,
                    self.max_retries,
                    exc,
                    wait,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(wait)

        return LLMResponse(
            content="",
            model=self.model,
            latency_ms=0,
            token_count=0,
            error=f"All {self.max_retries} attempts failed. Last error: {last_error}",
        )

    @abstractmethod
    async def _call(
        self,
        prompt: str,
        system: str,
        temperature: float,
    ) -> LLMResponse:
        """Provider-specific implementation. Must raise on error."""
        ...
