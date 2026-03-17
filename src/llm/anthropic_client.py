"""Anthropic (Claude) LLM client."""

from __future__ import annotations

import anthropic

from .base import LLMClient, LLMResponse


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str, **kwargs: object) -> None:
        super().__init__(model=model, **kwargs)  # type: ignore[arg-type]
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def _call(self, prompt: str, system: str, temperature: float) -> LLMResponse:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 2048,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        msg = await self._client.messages.create(**kwargs)
        content = msg.content[0].text if msg.content else ""
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)

        return LLMResponse(
            content=content,
            model=self.model,
            latency_ms=0,  # set by base class
            token_count=tokens,
        )
