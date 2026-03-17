"""
CI script: run the regression suite and write results to a JSON artifact.

Called by GitHub Actions after detect_affected.py.

Usage:
  python ci/run_suite.py --test-ids "id1 id2 id3" --commit-sha abc123 --output results.json
  python ci/run_suite.py  # runs full suite
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import typer
from src.config import get_settings
from src.models.result import RunTrigger
from src.registry import Registry
from src.runner import Runner
from src.storage import init_db, BaselineManager
from src.storage.database import get_engine, get_session_factory

app = typer.Typer()


@app.command()
def main(
    test_ids: str = typer.Option("", "--test-ids", help="Space-separated test case IDs"),
    commit_sha: str = typer.Option("", "--commit-sha"),
    branch_name: str = typer.Option("", "--branch-name"),
    output: str = typer.Option("ci_results.json", "--output"),
    update_baselines: bool = typer.Option(False, "--update-baselines"),
) -> None:
    exit_code = asyncio.run(_main_async(test_ids, commit_sha, branch_name, output, update_baselines))
    raise typer.Exit(exit_code)


async def _main_async(test_ids, commit_sha, branch_name, output, update_baselines) -> int:
    settings = get_settings()
    await init_db(settings.database_url)

    engine = get_engine(settings.database_url)
    factory = get_session_factory(engine)
    baseline_manager = BaselineManager(factory)

    registry = Registry(settings.tests_dir).load()

    if test_ids.strip():
        ids = set(test_ids.split())
        test_cases = [tc for tc in registry.all_cases() if tc.id in ids]
    else:
        test_cases = registry.all_cases()

    runner = Runner(settings, baseline_manager)
    suite_run = await runner.run_suite(
        test_cases,
        trigger=RunTrigger.PULL_REQUEST,
        commit_sha=commit_sha,
        branch_name=branch_name,
    )

    await baseline_manager.save_run(suite_run, test_cases)

    if update_baselines:
        await baseline_manager.update_baselines_from_run(suite_run, commit_sha)

    # Write results artifact
    results_data = {
        "run_id": suite_run.run_id,
        "total_tests": suite_run.total_tests,
        "passed_count": suite_run.passed_count,
        "failed_count": suite_run.failed_count,
        "regression_count": suite_run.regression_count,
        "has_regressions": suite_run.has_regressions,
        "results": [
            {
                "test_case_id": r.test_case_id,
                "test_case_name": r.test_case_name,
                "overall_score": r.overall_score,
                "baseline_score": r.baseline_score,
                "score_delta": r.score_delta,
                "regression_detected": r.regression_detected,
                "judge_verdict": r.judge_verdict,
                "passed": r.passed,
                "error": r.error,
            }
            for r in suite_run.results
        ],
    }

    Path(output).write_text(json.dumps(results_data, indent=2))
    print(f"Results written to {output}")
    print(f"Pass rate: {suite_run.overall_pass_rate:.0%} | Regressions: {suite_run.regression_count}")

    return 1 if suite_run.has_regressions else 0


if __name__ == "__main__":
    app()
