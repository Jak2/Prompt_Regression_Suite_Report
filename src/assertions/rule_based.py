"""
Rule-based assertions — deterministic, zero LLM cost, run first.

These are the cheapest and most reliable checks. A test case that fails
a rule-based assertion fails immediately, saving judge model API calls.

Supported assertion types:
  contains_keyword    — response contains ALL listed keywords
  not_contains        — response contains NONE of the listed phrases
  max_words           — word count ≤ limit
  min_words           — word count ≥ limit
  valid_json          — response is parseable JSON
  json_contains_key   — JSON response has all listed top-level keys
  starts_with         — response begins with expected_value
  not_starts_with     — response does NOT begin with expected_value
  language_is         — detected language == expected_value
  regex_match         — response matches pattern
  response_time_under — latency_ms ≤ max_seconds * 1000
  reading_level       — Flesch-Kincaid score in [min, max]
"""

from __future__ import annotations

import json
import re

import textstat

from ..models.result import AssertionResult
from ..models.test_case import AssertionConfig
from .base import Assertion

try:
    from langdetect import detect as _detect_lang
    _LANGDETECT_AVAILABLE = True
except Exception:
    _LANGDETECT_AVAILABLE = False


class RuleBasedAssertion(Assertion):
    """Dispatches to the correct rule handler based on config.type."""

    async def evaluate(
        self,
        response: str,
        config: AssertionConfig,
        context: dict,
    ) -> AssertionResult:
        handler = _HANDLERS.get(config.type)
        if handler is None:
            return AssertionResult(
                type=config.type,
                passed=False,
                score=0.0,
                explanation=f"Unknown assertion type: {config.type}",
                weight=config.weight,
            )
        passed, explanation = handler(response, config, context)
        return AssertionResult(
            type=config.type,
            passed=passed,
            score=1.0 if passed else 0.0,
            explanation=explanation,
            weight=config.weight,
        )


# ── Handlers (pure functions) ─────────────────────────────────────────────────

def _contains_keyword(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    lower = response.lower()
    missing = [k for k in config.keywords if k.lower() not in lower]
    if missing:
        return False, f"Missing keywords: {missing}"
    return True, f"All {len(config.keywords)} keyword(s) present"


def _not_contains(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    lower = response.lower()
    found = [p for p in config.phrases if p.lower() in lower]
    if found:
        return False, f"Forbidden phrases found: {found}"
    return True, "No forbidden phrases detected"


def _max_words(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    count = len(response.split())
    ok = count <= config.limit
    return ok, f"Word count {count} {'≤' if ok else '>'} limit {config.limit}"


def _min_words(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    count = len(response.split())
    ok = count >= config.limit
    return ok, f"Word count {count} {'≥' if ok else '<'} minimum {config.limit}"


def _valid_json(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    try:
        json.loads(response.strip())
        return True, "Response is valid JSON"
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"


def _json_contains_key(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    try:
        data = json.loads(response.strip())
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    missing = [k for k in config.keys if k not in data]
    if missing:
        return False, f"JSON missing keys: {missing}"
    return True, f"All required keys present: {config.keys}"


def _starts_with(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    ok = response.strip().startswith(config.expected_value)
    return ok, f"Response {'starts with' if ok else 'does not start with'} '{config.expected_value}'"


def _not_starts_with(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    stripped = response.strip()
    for phrase in (config.phrases or [config.expected_value]):
        if stripped.lower().startswith(phrase.lower()):
            return False, f"Response starts with forbidden phrase: '{phrase}'"
    return True, "Response does not start with any forbidden phrase"


def _language_is(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    if not _LANGDETECT_AVAILABLE:
        return True, "langdetect not installed — skipping language check"
    try:
        detected = _detect_lang(response)
    except Exception:
        return False, "Language detection failed"
    ok = detected == config.expected_value
    return ok, f"Detected language '{detected}', expected '{config.expected_value}'"


def _regex_match(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    match = bool(re.search(config.pattern, response, re.DOTALL))
    return match, f"Pattern '{config.pattern}' {'matched' if match else 'did not match'}"


def _response_time_under(
    _response: str, config: AssertionConfig, ctx: dict
) -> tuple[bool, str]:
    latency_ms: int = ctx.get("latency_ms", 0)
    limit_ms = int(config.max_seconds * 1000)
    ok = latency_ms <= limit_ms
    return ok, f"Latency {latency_ms}ms {'≤' if ok else '>'} {limit_ms}ms"


def _reading_level(
    response: str, config: AssertionConfig, _ctx: dict
) -> tuple[bool, str]:
    score = textstat.flesch_reading_ease(response)
    ok = config.reading_level_min <= score <= config.reading_level_max
    return ok, (
        f"Flesch score {score:.1f} "
        f"({'in' if ok else 'out of'} range "
        f"[{config.reading_level_min}, {config.reading_level_max}])"
    )


_HANDLERS = {
    "contains_keyword": _contains_keyword,
    "not_contains": _not_contains,
    "max_words": _max_words,
    "min_words": _min_words,
    "valid_json": _valid_json,
    "json_contains_key": _json_contains_key,
    "starts_with": _starts_with,
    "not_starts_with": _not_starts_with,
    "language_is": _language_is,
    "regex_match": _regex_match,
    "response_time_under": _response_time_under,
    "reading_level": _reading_level,
}

RULE_BASED_TYPES = set(_HANDLERS.keys())
