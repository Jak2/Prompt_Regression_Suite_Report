"""
CI script: post regression results as a GitHub PR comment.

Reads the JSON artifact from run_suite.py and posts/updates a PR comment.
Updates the existing comment if one was posted in a previous CI run on the same PR
(keeps the PR thread clean — one comment, always current).

Usage:
  python ci/post_comment.py --results ci_results.json --pr-number 42
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import typer

app = typer.Typer()

_COMMENT_MARKER = "<!-- prompt-regression-suite-comment -->"


@app.command()
def main(
    results: str = typer.Option("ci_results.json", "--results"),
    pr_number: int = typer.Option(..., "--pr-number"),
) -> None:
    data = json.loads(Path(results).read_text())
    comment_body = _build_comment(data)

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPO", os.environ.get("GITHUB_REPOSITORY", ""))

    if not token or not repo:
        print("GITHUB_TOKEN and GITHUB_REPO required — printing comment to stdout instead:\n")
        print(comment_body)
        return

    _post_or_update_comment(token, repo, pr_number, comment_body)


def _build_comment(data: dict) -> str:
    total = data["total_tests"]
    passed = data["passed_count"]
    regressions = data["regression_count"]
    has_reg = data["has_regressions"]

    badge = "🔴 FAILED" if has_reg else "🟢 PASSED"
    lines = [
        _COMMENT_MARKER,
        f"## {badge} — Prompt Regression Suite",
        "",
        f"**{passed}/{total}** tests passed | **{regressions}** regression(s) detected",
        "",
    ]

    # Regression table
    reg_results = [r for r in data["results"] if r["regression_detected"]]
    if reg_results:
        lines += [
            "### Regressions",
            "",
            "| Test Case | Prev | Now | Delta | Verdict |",
            "|-----------|------|-----|-------|---------|",
        ]
        for r in reg_results:
            lines.append(
                f"| {r['test_case_name'][:40]} "
                f"| {r['baseline_score']:.3f} "
                f"| {r['overall_score']:.3f} "
                f"| {r['score_delta']:+.3f} "
                f"| {r['judge_verdict'][:60]} |"
            )
        lines.append("")

    # Stable tests count
    stable = total - regressions - sum(1 for r in data["results"] if r.get("error"))
    lines.append(f"**{stable}** test(s) stable vs baseline")

    if has_reg:
        lines += ["", "> ⚠️ **Action required:** investigate regressions before merging."]
    else:
        lines += ["", "> ✅ **Safe to merge** — no prompt quality regressions detected."]

    return "\n".join(lines)


def _post_or_update_comment(token: str, repo: str, pr_number: int, body: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    base = f"https://api.github.com/repos/{repo}"

    # Check for existing comment
    resp = httpx.get(f"{base}/issues/{pr_number}/comments", headers=headers, timeout=30)
    existing_id = None
    for comment in resp.json():
        if _COMMENT_MARKER in comment.get("body", ""):
            existing_id = comment["id"]
            break

    if existing_id:
        httpx.patch(
            f"{base}/issues/comments/{existing_id}",
            headers=headers,
            json={"body": body},
            timeout=30,
        )
        print(f"Updated existing PR comment #{existing_id}")
    else:
        httpx.post(
            f"{base}/issues/{pr_number}/comments",
            headers=headers,
            json={"body": body},
            timeout=30,
        )
        print(f"Posted new PR comment on PR #{pr_number}")


if __name__ == "__main__":
    app()
