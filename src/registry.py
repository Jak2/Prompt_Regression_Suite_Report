"""
Test Case Registry — discovers, parses, and validates all .prompt-test.yaml files.

Design decisions:
- Glob walk is synchronous; the registry is loaded once and cached.
- Validation errors surface immediately at load time, not during a test run.
- The reverse index (prompt_file → [test_cases]) powers selective CI execution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from .models import TestCase

logger = logging.getLogger(__name__)

YAML_SUFFIX = ".prompt-test.yaml"


class Registry:
    """Loads and indexes all test cases from a directory tree."""

    def __init__(self, tests_dir: Path) -> None:
        self.tests_dir = tests_dir
        self._cases: dict[str, TestCase] = {}         # id → TestCase
        self._reverse_index: dict[str, list[str]] = {} # prompt_file → [ids]

    # ── Public API ─────────────────────────────────────────────────────────────

    def load(self) -> "Registry":
        """Walk tests_dir, parse every YAML file, populate indexes."""
        yaml_files = list(self.tests_dir.rglob(f"*{YAML_SUFFIX}"))
        if not yaml_files:
            logger.warning("No test case files found in %s", self.tests_dir)
        for path in yaml_files:
            self._load_file(path)
        logger.info("Registry loaded %d test cases", len(self._cases))
        return self

    def all_cases(self) -> list[TestCase]:
        return list(self._cases.values())

    def get(self, test_id: str) -> Optional[TestCase]:
        return self._cases.get(test_id)

    def affected_by(self, changed_files: list[str]) -> list[TestCase]:
        """Return only the test cases that reference one of the changed files."""
        affected_ids: set[str] = set()
        for f in changed_files:
            norm = _normalize(f)
            for prompt_key, ids in self._reverse_index.items():
                if _normalize(prompt_key) == norm or norm.endswith(_normalize(prompt_key)):
                    affected_ids.update(ids)
        return [self._cases[i] for i in affected_ids if i in self._cases]

    def should_run_full_suite(self, changed_files: list[str]) -> bool:
        """Run full suite when >30% of prompt files changed (systemic change)."""
        all_prompt_files = set(self._reverse_index.keys())
        if not all_prompt_files:
            return True
        changed_prompts = {
            pf for pf in all_prompt_files
            if any(_normalize(cf).endswith(_normalize(pf)) for cf in changed_files)
        }
        return len(changed_prompts) / len(all_prompt_files) > 0.30

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _load_file(self, path: Path) -> None:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            logger.error("YAML parse error in %s: %s", path, e)
            return

        if not isinstance(raw, dict):
            logger.error("Expected a YAML mapping in %s, got %s", path, type(raw))
            return

        try:
            tc = TestCase(**raw, file_path=str(path))
        except ValidationError as e:
            logger.error("Validation error in %s:\n%s", path, e)
            return

        self._cases[tc.id] = tc
        prompt_key = tc.prompt_template
        self._reverse_index.setdefault(prompt_key, []).append(tc.id)


def _normalize(p: str) -> str:
    """Normalise path separators for cross-platform comparison."""
    return p.replace("\\", "/").strip("/")
