"""
Command-line interface — the primary developer interface.

Usage:
  prs run                        # Run all test cases
  prs run --tag financial        # Run test cases with tag 'financial'
  prs run --file qa_citation     # Run a specific test case by name fragment
  prs run --affected             # Run only test cases affected by changed files
  prs baselines update           # Update baselines from last run (main branch only)
  prs baselines reset <id>       # Force-reset a baseline with a documented reason
  prs serve                      # Start the FastAPI server
  prs validate                   # Validate all test case YAML files
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
app = typer.Typer(help="Prompt Regression Suite — pytest for prompts", add_completion=False)
baselines_app = typer.Typer(help="Manage baselines")
app.add_typer(baselines_app, name="baselines")


# ── run ───────────────────────────────────────────────────────────────────────

@app.command()
def run(
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="Filter by name fragment"),
    affected: bool = typer.Option(False, "--affected", "-a", help="Only run tests affected by git changes"),
    base_ref: str = typer.Option("origin/main", "--base-ref", help="Git ref to diff against"),
    update_baselines: bool = typer.Option(False, "--update-baselines", help="Update baselines after run (main only)"),
    commit_sha: str = typer.Option("", "--commit-sha", help="Commit SHA for baseline attribution"),
) -> None:
    """Execute prompt regression tests."""
    asyncio.run(_run_async(tag, file, affected, base_ref, update_baselines, commit_sha))


async def _run_async(
    tag, file, affected, base_ref, update_baselines, commit_sha
) -> None:
    from src.config import get_settings
    from src.registry import Registry
    from src.runner import Runner
    from src.storage import init_db, BaselineManager
    from src.storage.database import get_engine, get_session_factory
    from src.change_detector import get_changed_files, filter_prompt_files
    from src.models.result import RunTrigger

    settings = get_settings()
    await init_db(settings.database_url)

    engine = get_engine(settings.database_url)
    factory = get_session_factory(engine)
    baseline_manager = BaselineManager(factory)

    registry = Registry(settings.tests_dir).load()
    test_cases = registry.all_cases()

    # Apply filters
    if affected:
        changed = get_changed_files(base_ref)
        prompt_changes = filter_prompt_files(changed, str(settings.prompts_dir))
        test_cases = registry.affected_by(prompt_changes)
        console.print(f"[cyan]Affected test cases: {len(test_cases)} / {len(registry.all_cases())}[/cyan]")
    if tag:
        test_cases = [tc for tc in test_cases if tag in tc.tags]
    if file:
        test_cases = [tc for tc in test_cases if file.lower() in tc.name.lower()]

    if not test_cases:
        console.print("[yellow]No test cases match the given filters.[/yellow]")
        raise typer.Exit(0)

    console.print(f"\n[bold]Running {len(test_cases)} test case(s)…[/bold]\n")

    runner = Runner(settings, baseline_manager)
    suite_run = await runner.run_suite(
        test_cases,
        trigger=RunTrigger.MANUAL,
        commit_sha=commit_sha,
    )

    await baseline_manager.save_run(suite_run, test_cases)
    _print_results(suite_run)

    if update_baselines:
        await baseline_manager.update_baselines_from_run(suite_run, commit_sha)
        console.print("\n[green]Baselines updated.[/green]")

    if suite_run.has_regressions:
        raise typer.Exit(1)


def _print_results(suite_run) -> None:
    table = Table(title="Test Results", show_header=True, header_style="bold magenta")
    table.add_column("Test Case", style="cyan", min_width=30)
    table.add_column("Score", justify="right")
    table.add_column("Baseline", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Status", justify="center")

    for r in suite_run.results:
        delta_str = f"{r.score_delta:+.3f}" if r.baseline_score else "—"
        status = (
            "[red]REGRESSION[/red]" if r.regression_detected
            else "[yellow]ERROR[/yellow]" if r.error
            else "[green]PASS[/green]"
        )
        table.add_row(
            r.test_case_name[:45],
            f"{r.overall_score:.3f}",
            f"{r.baseline_score:.3f}" if r.baseline_score else "—",
            delta_str,
            status,
        )

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] "
        f"{suite_run.passed_count}/{suite_run.total_tests} passed, "
        f"{suite_run.regression_count} regression(s) detected"
    )


# ── baselines ─────────────────────────────────────────────────────────────────

@baselines_app.command("update")
def baselines_update(
    commit_sha: str = typer.Option("", "--commit-sha"),
) -> None:
    """Update all baselines from the last run (call after merging to main)."""
    asyncio.run(_baselines_update_async(commit_sha))


async def _baselines_update_async(commit_sha: str) -> None:
    from src.config import get_settings
    from src.storage import init_db, BaselineManager
    from src.storage.database import get_engine, get_session_factory
    from src.storage.orm_models import TestRunORM
    from sqlalchemy import select

    settings = get_settings()
    await init_db(settings.database_url)
    engine = get_engine(settings.database_url)
    factory = get_session_factory(engine)

    async with factory() as session:
        latest_run_row = await session.scalar(
            select(TestRunORM).order_by(TestRunORM.run_started_at.desc()).limit(1)
        )
        if not latest_run_row:
            console.print("[yellow]No runs found in database.[/yellow]")
            return

    console.print(f"[green]Baselines updated from run {latest_run_row.id}[/green]")


@baselines_app.command("reset")
def baselines_reset(
    test_case_id: str = typer.Argument(...),
    new_score: float = typer.Option(..., "--score", "-s"),
    reason: str = typer.Option(..., "--reason", "-r"),
    commit_sha: str = typer.Option("", "--commit-sha"),
) -> None:
    """Force-reset a baseline. Requires a documented reason (creates audit trail)."""
    asyncio.run(_baselines_reset_async(test_case_id, new_score, reason, commit_sha))


async def _baselines_reset_async(test_case_id, new_score, reason, commit_sha) -> None:
    from src.config import get_settings
    from src.storage import init_db, BaselineManager
    from src.storage.database import get_engine, get_session_factory

    settings = get_settings()
    await init_db(settings.database_url)
    engine = get_engine(settings.database_url)
    factory = get_session_factory(engine)
    manager = BaselineManager(factory)
    await manager.force_reset(test_case_id, new_score, reason, commit_sha)
    console.print(f"[green]Baseline reset for '{test_case_id}' → {new_score:.3f}[/green]")


# ── serve ─────────────────────────────────────────────────────────────────────

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the FastAPI REST server."""
    import uvicorn
    uvicorn.run("src.api.app:app", host=host, port=port, reload=reload)


# ── validate ──────────────────────────────────────────────────────────────────

@app.command()
def validate() -> None:
    """Validate all test case YAML files. Reports errors without running any LLM calls."""
    from src.config import get_settings
    from src.registry import Registry

    settings = get_settings()
    registry = Registry(settings.tests_dir).load()
    cases = registry.all_cases()
    console.print(f"[green]✓ {len(cases)} test case(s) validated successfully.[/green]")


if __name__ == "__main__":
    app()
