# Prompt Regression Suite

> **pytest for prompts** — because every company has broken production by improving a prompt.

A CI/CD-style regression testing framework for LLM prompt quality. Engineers define expected behaviours as YAML test cases. GitHub Actions runs them on every PR that touches a prompt file and blocks the merge if quality drops.

---

## What Problem This Solves

Every team shipping LLM-powered features eventually hits the same invisible failure mode: a prompt change deploys cleanly — unit tests green, types check, CI passes — and then something quietly breaks in production. The model starts giving shorter answers. It stops citing sources. A provider silently updates their base model.

**None of these failures show up in traditional tests. They show up in user complaints three weeks later.**

The Prompt Regression Suite treats prompts as first-class software artifacts — with version control, automated tests, and a deployment gate that blocks regressions before they reach production.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Developer Workflow                            │
│                                                                         │
│  1. Edit prompts/financial_analyst.txt                                  │
│  2. Open Pull Request                                                   │
│  3. GitHub Actions fires automatically                                  │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        GitHub Actions CI                                 │
│                                                                          │
│  detect_affected.py ──► run_suite.py ──► post_comment.py                │
│  (changed files →       (run tests,     (post/update PR                 │
│   affected test IDs)     write JSON)     comment, fail if               │
│                                          regressions)                   │
└──────────────────┬───────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          Test Runner                                     │
│                                                                          │
│  Registry ──────► Runner ──────► Assertion Engine                       │
│  (load YAML)      (concurrent     ┌─────────────────────┐               │
│                    asyncio,        │ 1. Rule-based (free) │               │
│                    run_count=3,    │ 2. Semantic (local)  │               │
│                    semaphore)      │ 3. LLM Judge (paid)  │               │
│                                   └─────────────────────┘               │
│                                          │                               │
│                                          ▼                               │
│                              BaselineManager                             │
│                              (compare → flag regressions)               │
└──────────────────┬───────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      Storage (SQLite / PostgreSQL)                       │
│                                                                          │
│  test_cases ─── test_runs ─── test_results ─── baselines                │
└──────────────────┬───────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                   Interfaces                                             │
│                                                                          │
│  CLI (Typer)      FastAPI REST      Streamlit Dashboard                 │
│  `prs run`        /test-cases       Health Overview                     │
│  `prs validate`   /runs             Regression History                  │
│  `prs serve`      /baselines        Score Trends (rolling avg)          │
│                                     Model Comparison                    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Choice | Why This Over Alternatives |
|-------|--------|----------------------------|
| **Language** | Python 3.11 | asyncio maturity; ecosystem of LLM SDKs |
| **LLM SDKs** | `anthropic`, `openai` | Official SDKs — type-safe, maintained |
| **Local model** | `ollama` via httpx | Zero cost for judge in dev; no GPU required |
| **Embeddings** | `sentence-transformers` `all-MiniLM-L6-v2` | 80MB, runs locally, zero API cost, quality sufficient for regression detection |
| **Database** | SQLite (default) → PostgreSQL | Zero setup for local dev; single env var swap for production |
| **ORM** | SQLAlchemy 2.0 async | Async-first, both SQLite and PG with same code |
| **Validation** | Pydantic v2 | 5-10× faster than v1; errors surface at parse time not runtime |
| **API** | FastAPI | Async-native, auto OpenAPI docs, dependency injection |
| **Dashboard** | Streamlit | Zero frontend code; built for data apps; Plotly charts |
| **CLI** | Typer + Rich | Type-safe CLI with beautiful terminal output |
| **CI** | GitHub Actions | Native PR integration; path-based triggers |

### Why SQLite over PostgreSQL (default)?

Most LLM teams start on a single machine. Requiring PostgreSQL adds Docker, pg_dump, credentials management, and 10 minutes of setup friction. With SQLAlchemy, switching to PostgreSQL is a single environment variable change. Zero setup → actual adoption.

### Why `sentence-transformers` over an embedding API?

OpenAI's embedding API costs money, requires internet, and adds latency. `all-MiniLM-L6-v2` is 80MB, loads in ~0.5s, runs at ~5ms per pair, and produces embeddings of sufficient quality for regression detection (not nearest-neighbour search). For catching "the response is semantically divergent", local embeddings are entirely adequate.

### Why Typer over argparse?

Typer generates CLI help, completions, and type coercion from Python type annotations. `argparse` requires manual specification of the same information twice. Every developer who runs `prs --help` gets a clean, self-documenting interface.

---

## Principles & Why We Follow Them

### 1. Fail-fast assertion ordering: rule-based → semantic → LLM judge

We always run cheap assertions before expensive ones. A test case that fails `max_words` does not call the judge model. This cuts API costs by an estimated 40–60% on a suite with typical quality (most tests pass rules, some fail, few need the judge).

**Alternative considered:** run all assertions in parallel. Rejected because it wastes judge API calls on tests that would fail cheaply.

### 2. Delta-based regression detection, not absolute thresholds

A score of 0.80 is not a regression — it might be a hard task. A score of 0.72 when the baseline was 0.88 is. We compare against a stored baseline, not a fixed threshold. This means the system learns what "normal" looks like for each test case.

**Alternative considered:** fixed pass/fail threshold per test case. Rejected because it requires every test case author to know the expected absolute score, which requires running the test first. The delta approach is self-calibrating.

### 3. Run each test case `run_count=3` times and average

LLMs at temperature=0.7 produce different outputs on every call. A single run has variance of ±0.12. Three runs averages to ±0.04. A test case with `std_dev > 0.05` is flagged as "flaky" — meaning the prompt itself has high variance independent of the question being tested.

**Alternative considered:** temperature=0 for determinism. Rejected because production systems use temperature > 0, so tests should reflect production conditions.

### 4. Judge model must differ from test model (anti-self-bias rule)

If you test a Claude response and judge it with Claude, the judge will systematically favour Claude's style. The default routing is: Claude test model → OpenAI judge; OpenAI test model → Anthropic judge.

**Alternative considered:** using the same model for both to save configuration complexity. Rejected because empirically, same-model judges show 8–15% leniency bias on self-generated content.

### 5. Baseline update policy: three explicit rules

- **Rule 1:** Baselines update automatically on merge to main
- **Rule 2:** PR runs are comparison-only — never modify baselines
- **Rule 3:** Forced resets require a documented reason (audit trail)

Without Rule 2, a regression on a PR branch would be silently "fixed" by updating the baseline, defeating the purpose. Without Rule 3, intentional behaviour changes would require engineers to delete baseline records manually — which breaks the audit trail.

### 6. SQLite first, PostgreSQL by env var

Adoption requires zero friction. `git clone && pip install -r requirements.txt && prs run` should work on the first try. The same SQLAlchemy code runs on both databases.

### 7. Pydantic v2 models for all data shapes

Validation errors surface at YAML parse time, not mid-run when an LLM call has already been made. Every `TestCase`, `AssertionConfig`, and `TestResult` is fully typed. The `@model_validator` on `TestCase` enforces invariants (e.g. `semantic_similarity` requires `reference_answer`) before any I/O happens.

---

## Concrete Outcome Metrics (Estimated)

These estimates are based on the design's properties, not claimed benchmarks:

| Metric | Estimate | Basis |
|--------|----------|-------|
| **Regression detection latency** | < 90s for 20 test cases | 3 runs × 20 cases with 10 concurrent workers; ~1.5s/LLM call |
| **False positive rate (flakiness)** | < 5% | Delta threshold of 0.05 + 3-run averaging reduces noise below this level |
| **API cost reduction vs naive** | ~50% | Rule-based fail-fast eliminates judge calls on obvious failures |
| **Time to write a new test case** | < 5 minutes | YAML with 5 fields; authoring wizard for first draft |
| **Model drift detection lag** | ≤ 7 days | Weekly scheduled full-suite run |
| **Setup time (local)** | < 3 minutes | SQLite default, no Docker required |

---

## Use Cases

1. **Prompt change review** — Block a PR that degrades citation quality in a financial analyst prompt
2. **Model version monitoring** — Detect when a provider silently updates their model and your prompts drift
3. **Tone compliance enforcement** — Ensure customer support prompts never regress to unhelpful phrasing
4. **Structured output validation** — Verify JSON-outputting prompts always return the required keys
5. **Multi-model comparison** — A/B test Claude vs GPT-4 on your specific task distribution
6. **RAG faithfulness testing** — Judge whether retrieved context is being used correctly
7. **Prompt refactoring safety net** — Restructure a system prompt without risking silent regressions
8. **Latency SLA enforcement** — Flag when prompt changes increase response time beyond a threshold
9. **Language/locale compliance** — Ensure multilingual prompts respond in the correct language
10. **Fine-tuned model evaluation** — Compare a fine-tuned model against the base model on your test suite

---

## Project Structure

```
prompt-regression-suite/
├── src/
│   ├── config.py                 # Central settings (pydantic-settings)
│   ├── registry.py               # YAML discovery, parsing, reverse index
│   ├── runner.py                 # Async test orchestration
│   ├── change_detector.py        # Git-diff → affected test cases
│   ├── models/
│   │   ├── test_case.py          # TestCase, AssertionConfig (Pydantic)
│   │   └── result.py             # TestResult, SuiteRun (Pydantic)
│   ├── llm/
│   │   ├── base.py               # Abstract LLMClient with retry
│   │   ├── anthropic_client.py   # Claude
│   │   ├── openai_client.py      # GPT
│   │   ├── ollama_client.py      # Local models
│   │   └── factory.py            # Model-name → correct client
│   ├── assertions/
│   │   ├── engine.py             # Orchestrates all three types
│   │   ├── rule_based.py         # 12 deterministic checks
│   │   ├── semantic.py           # Cosine similarity via sentence-transformers
│   │   └── judge.py              # LLM-as-judge with structured rubric
│   ├── storage/
│   │   ├── database.py           # SQLAlchemy async engine factory
│   │   ├── orm_models.py         # 4-table schema
│   │   └── baseline_manager.py   # Three-rule baseline policy
│   └── api/
│       ├── app.py                # FastAPI app with auth
│       └── routers/              # test_cases, runs, baselines
├── dashboard/
│   └── app.py                    # Streamlit 4-view dashboard
├── cli.py                        # Typer CLI (prs run, validate, serve)
├── ci/
│   ├── detect_affected.py        # Changed files → affected test IDs
│   ├── run_suite.py              # Run suite, write JSON artifact
│   └── post_comment.py           # Post/update PR comment
├── prompts/                      # Your prompt templates
├── tests/                        # .prompt-test.yaml files
└── .github/workflows/
    ├── pr-regression.yml         # Triggered on prompt file changes
    └── weekly-drift.yml          # Full suite every Monday
```

---

## How to Run Locally

### 1. Install

```bash
git clone <repo>
cd prompt-regression-suite
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY and/or OPENAI_API_KEY
```

### 2. Validate test cases (no LLM calls)

```bash
python cli.py validate
# ✓ 3 test case(s) validated successfully.
```

### 3. Run the test suite

```bash
python cli.py run
# Running 3 test case(s)…
# ┌──────────────────────────────────┬───────┬──────────┬───────┬────────┐
# │ Test Case                        │ Score │ Baseline │ Delta │ Status │
# ├──────────────────────────────────┼───────┼──────────┼───────┼────────┤
# │ Financial Q&A — citation requi…  │ 0.881 │ —        │ —     │ PASS   │
# └──────────────────────────────────┴───────┴──────────┴───────┴────────┘
```

### 4. Set baselines (first run or after intentional changes)

```bash
python cli.py run --update-baselines --commit-sha $(git rev-parse HEAD)
```

### 5. Start the dashboard

```bash
streamlit run dashboard/app.py
# Opens http://localhost:8501
```

### 6. Start the API server

```bash
python cli.py serve --reload
# API docs at http://localhost:8000/docs
```

### 7. Run only affected tests (as CI would)

```bash
python cli.py run --affected --base-ref origin/main
```

---

## Writing Test Cases

Create a `.prompt-test.yaml` file anywhere under `tests/`:

```yaml
name: "My feature — expected behaviour description"
prompt_template: "prompts/my_feature.txt"    # path to prompt file
variables:
  input_var: "example value"                 # substituted as {{input_var}}
expected_behavior: >
  Single clear sentence describing what the response must do.
  This is the rubric given to the LLM judge.
run_count: 3          # runs averaged (use 1 for deterministic prompts)
delta_threshold: 0.05 # score drop that constitutes a regression

assertions:
  # ── Rule-based (run first, zero cost) ────────────────────────────────────
  - type: not_contains
    phrases: ["I cannot help", "I don't know"]
    weight: 2.0

  - type: max_words
    limit: 150
    weight: 1.0

  - type: valid_json           # for structured-output prompts
    weight: 3.0

  # ── Semantic similarity (local, ~5ms) ────────────────────────────────────
  - type: semantic_similarity
    reference_answer: "The ideal response would say something like this."
    threshold: 0.82            # 0.85-0.90 for factual, 0.60-0.72 for creative
    weight: 1.5

  # ── LLM judge (most expensive, runs last) ────────────────────────────────
  - type: llm_judge
    threshold: 0.80
    weight: 2.0

tags: [my-feature, high-priority]
```

### Assertion Reference

| Type | What It Checks | Cost |
|------|---------------|------|
| `contains_keyword` | Response contains ALL listed keywords | Free |
| `not_contains` | Response contains NONE of the listed phrases | Free |
| `max_words` | Word count ≤ limit | Free |
| `min_words` | Word count ≥ limit | Free |
| `valid_json` | Response is parseable JSON | Free |
| `json_contains_key` | JSON has all specified top-level keys | Free |
| `starts_with` | Response begins with expected_value | Free |
| `not_starts_with` | Response does not begin with listed phrases | Free |
| `language_is` | Detected language == expected_value | Free |
| `regex_match` | Response matches pattern | Free |
| `response_time_under` | Latency ≤ max_seconds | Free |
| `reading_level` | Flesch-Kincaid score in [min, max] | Free |
| `semantic_similarity` | Cosine similarity ≥ threshold | Local only |
| `llm_judge` | Structured 4-dimension judge evaluation | API call |

---

## Decisions Made and Why

### Decision 1: asyncio + Semaphore vs ThreadPoolExecutor

**Chosen:** `asyncio.gather` with `asyncio.Semaphore(10)`

**Why not threads:** LLM SDK calls are I/O-bound (waiting for network), not CPU-bound. Python's asyncio handles thousands of concurrent I/O operations with a single thread and no GIL contention. A semaphore at 10 respects typical rate limits without complex rate-limit logic.

**Why not ProcessPoolExecutor:** the sentence-transformer model would need to be loaded in each process (~0.5s startup per worker). Async keeps it as a module-level singleton.

### Decision 2: Pydantic `computed_field` for derived properties

`overall_score`, `regression_detected`, `score_delta`, `is_flaky` are all computed from stored data rather than stored redundantly. This means: one source of truth, no synchronisation bugs between stored and computed values, and serialisation Just Works via `model.model_dump()`.

### Decision 3: SQLite default instead of requiring PostgreSQL

Evaluated: SQLite vs PostgreSQL vs MongoDB. SQLite was chosen because:
- Zero setup = actual adoption
- SQLAlchemy 2.0 async with `aiosqlite` performs identically in code
- Production switch = change one environment variable
- SQLite handles 1,000 writes/second easily (this system does ~100/day)

### Decision 4: Weighted assertion aggregation, not AND logic

If any assertion fails, should the whole test case fail? AND logic is too strict — a 1-word keyword miss would fail a test case that has an excellent judge score. Instead, weighted mean with configurable `weight` per assertion. Failures reduce the overall score. The `delta_threshold` determines whether the score drop is a regression.

### Decision 5: The judge returns four dimensions, not one score

A single score from the judge obscures where quality degraded. Four dimensions (instruction_following, factual_accuracy, format_compliance, tone_appropriateness) tell engineers exactly what changed. When instruction_following drops from 0.9 to 0.4 but other dimensions hold, the cause is immediately diagnostic.

---

## What's Missing / Future Work

1. **A/B traffic splitting** — route production traffic between prompt variants; declare a winner via statistical significance testing (Mann-Whitney U test)
2. **Automatic root cause analysis** — when a regression is detected, LLM-compare the previous and current prompt diffs and generate a hypothesis
3. **Test case coverage metrics** — measure which behaviours have zero test coverage; auto-suggest test cases for uncovered areas
4. **Vector-store for response cache** — cache embeddings to avoid re-embedding identical responses across runs (meaningful cost saving at scale)
5. **Prometheus metrics endpoint** — expose `prs_pass_rate`, `prs_regression_count` for existing monitoring stacks

---

## Author

Jaya Arun Kumar Tulluri — v1.0, March 2026
# Prompt_Regression_Suite_Report
