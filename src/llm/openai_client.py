"""OpenAI (GPT) LLM client."""

from __future__ import annotations

from openai import AsyncOpenAI

from .base import LLMClient, LLMResponse


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str, **kwargs: object) -> None:
        super().__init__(model=model, **kwargs)  # type: ignore[arg-type]
        self._client = AsyncOpenAI(api_key=api_key)

    async def _call(self, prompt: str, system: str, temperature: float) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=2048,
        )
        content = resp.choices[0].message.content or ""
        tokens = resp.usage.total_tokens if resp.usage else 0

        return LLMResponse(
            content=content,
            model=self.model,
            latency_ms=0,
            token_count=tokens,
        )
