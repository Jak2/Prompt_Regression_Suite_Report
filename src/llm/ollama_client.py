"""Ollama (local) LLM client — zero API cost, useful for judge in dev environments."""

from __future__ import annotations

import httpx

from .base import LLMClient, LLMResponse


class OllamaClient(LLMClient):
    def __init__(self, base_url: str, model: str, **kwargs: object) -> None:
        super().__init__(model=model, **kwargs)  # type: ignore[arg-type]
        self._base_url = base_url.rstrip("/")

    async def _call(self, prompt: str, system: str, temperature: float) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            content=data.get("response", ""),
            model=self.model,
            latency_ms=0,
            token_count=data.get("eval_count", 0),
        )
