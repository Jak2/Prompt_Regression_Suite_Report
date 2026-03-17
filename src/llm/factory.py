"""Factory that builds the correct LLM client from settings."""

from __future__ import annotations

from ..config import Settings
from .anthropic_client import AnthropicClient
from .base import LLMClient
from .ollama_client import OllamaClient
from .openai_client import OpenAIClient


def get_client(model: str, settings: Settings) -> LLMClient:
    """
    Routing rules (checked in order):
    1. Model starts with 'claude-' → Anthropic
    2. Model starts with 'gpt-' or 'o1'/'o3' → OpenAI
    3. Anything else → Ollama (local)
    """
    kwargs = dict(timeout=settings.llm_timeout_seconds, max_retries=settings.llm_max_retries)

    if model.startswith("claude-"):
        return AnthropicClient(api_key=settings.anthropic_api_key, model=model, **kwargs)
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return OpenAIClient(api_key=settings.openai_api_key, model=model, **kwargs)
    # Fallback → Ollama (also used for local fine-tuned models)
    return OllamaClient(base_url=settings.ollama_base_url, model=model, **kwargs)
