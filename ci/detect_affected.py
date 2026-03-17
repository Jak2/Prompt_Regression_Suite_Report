"""
CI script: detect which test cases are affected by changed prompt files.

Called by GitHub Actions before running the test suite.
Outputs JSON to stdout for the next workflow step to consume.

Usage:
  python ci/detect_affected.py --changed-files "prompts/financial_analyst.txt prompts/support.txt"
  python ci/detect_affected.py  # auto-detects from git diff
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import typer
from src.change_detector import get_changed_files, filter_prompt_files
from src.config import get_settings
from src.registry import Registry

app = typer.Typer()


@app.command()
def main(
    changed_files: str = typer.Option(
        "", "--changed-files", help="Space-separated list of changed files (overrides git detection)"
    ),
    base_ref: str = typer.Option("origin/main", "--base-ref"),
) -> None:
    settings = get_settings()
    registry = Registry(settings.tests_dir).load()

    if changed_files:
        all_changed = [f.strip() for f in changed_files.split() if f.strip()]
    else:
        all_changed = get_changed_files(base_ref)

    prompt_changes = filter_prompt_files(all_changed, str(settings.prompts_dir))
    run_full_suite = registry.should_run_full_suite(prompt_changes)
    affected = registry.affected_by(prompt_changes)

    output = {
        "changed_files": all_changed,
        "prompt_changes": prompt_changes,
        "run_full_suite": run_full_suite,
        "affected_test_ids": [tc.id for tc in affected],
        "affected_count": len(affected),
        "total_count": len(registry.all_cases()),
    }

    print(json.dumps(output, indent=2))

    # Set GitHub Actions output variables
    import os
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"run_full_suite={str(run_full_suite).lower()}\n")
            fh.write(f"affected_count={len(affected)}\n")


if __name__ == "__main__":
    app()
