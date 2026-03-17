"""
Change Detector — maps Git-changed files to affected test cases.

Used by GitHub Actions to avoid running the full suite on every PR.
A PR changing 3 prompt files might trigger 12 of 80 test cases.

The 30% heuristic: if >30% of all prompt files changed, treat it as a
systemic change and run the full suite. This catches refactors that
touch many files at once.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def get_changed_files(base_ref: str = "origin/main") -> list[str]:
    """
    Return list of files changed vs base_ref.
    Works in GitHub Actions (GITHUB_BASE_REF is set) and locally.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except subprocess.CalledProcessError:
        # Fallback: compare working tree to HEAD
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
        )
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def filter_prompt_files(changed_files: list[str], prompts_dir: str = "prompts") -> list[str]:
    """Keep only files that live in the prompts directory."""
    prefix = prompts_dir.rstrip("/") + "/"
    return [f for f in changed_files if f.startswith(prefix)]
