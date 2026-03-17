# Prompt Regression Suite

> **pytest for prompts** — because every company has broken production by improving a prompt.

A CI/CD-style regression testing framework designed specifically for LLM prompt quality and behavior. By defining expected behaviors as YAML test cases, engineering teams can automatically run regression tests in GitHub Actions every time a prompt file is modified—blocking merges if prompt quality drops.

---

## 🛑 What Problem This Solves

Every team shipping LLM-powered features eventually hits the same invisible failure mode: a prompt change deploys cleanly—unit tests are green, types check, CI passes—and then something quietly breaks in production.
* The model starts giving shorter answers.
* It stops citing sources properly.
* A provider silently updates their base model, changing its baseline behavior.

**None of these failures show up in traditional tests. They show up in user complaints three weeks later.**

The Prompt Regression Suite solves this by treating your prompts as **first-class software artifacts**. It introduces version control, automated behavioral testing, and a deployment gate that blocks regressions *before* reaching your users.

---

## ✨ Functionality & Key Features

* **Fail-fast assertion pipeline**: Evaluates cheap, deterministic rule-based checks before triggering expensive semantic similarities or LLM-as-judge calls to optimize evaluation costs.
* **Delta-based regression detection**: Uses standard deviations across multi-run averages (e.g., at temperature=0.7) to flag actual regressions rather than relying on brittle, fixed thresholds.
* **Anti-self-bias evaluation**: Automatically routes judge calls to a different AI provider (e.g., Claude tests are reliably judged by OpenAI, not Claude).
* **CI/CD Native**: Blocks regressions safely inside GitHub Actions on PRs before merges are allowed.
* **Visual Dashboard**: A built-in Streamlit app that plots and tracks regression history and score trends over time.

---

## 👍 Pros & Benefits

1. **Massive Cost Savings (~50%)**: By employing a tiered assertion engine (rules -> local semantic -> paid judge), tests fail fast and cheap.
2. **Eliminates Testing Noise (<5% Flakiness)**: Multi-run averaging mitigates the randomness of LLM temperature outputs.
3. **Zero Setup Friction for Devs**: Uses local SQLite and `sentence-transformers` by default so devs can clone, install, and run locally without spinning up Docker or Postgres.
4. **Fast Execution**: Designed around `asyncio` batching, finishing a full suite in seconds instead of minutes.

---

## 🏗️ Architecture Flow Diagram

Below is the workflow of how a developer interacts with the system, from committing code to CI/CD blocking regressions.

```mermaid
flowchart TD
    %% Developer Workflow
    subgraph Dev["Developer Environment"]
        A[Edit Prompt File] --> B[Commit & Push]
        B --> C[Open Pull Request]
    end

    %% CI / Test Runner
    subgraph CI["GitHub Actions CI/CD"]
        C --> D[detect_affected.py]
        D -->|Identifies changed prompts| E[run_suite.py]
        
        %% Test Orchestration
        E --> F{Assertion Engine}
        F --> G[1. Rule-Based Checks]
        G -->|If Pass| H[2. Local Semantic Check]
        H -->|If Pass| I[3. LLM-as-Judge API]
    end
    
    %% Storage & Outcome
    subgraph DB["Storage (SQLite/Postgres)"]
        J[(Baselines & Test Results)]
    end

    I -->|Record Scores| J
    J -->|Compare Deltas| K{Regression Detected?}
    
    K -->|Yes| L[❌ Block PR Merge & Post Comment]
    K -->|No| M[✅ Allow PR Merge]

    %% Dashboard interaction
    subgraph Dashboard["Interfaces"]
        N[Streamlit Dashboard] -.->|Reads| J
        O[FastAPI REST API] -.->|Reads/Writes| J
    end
```

---

## 🔌 Communication Between Files

The system architecture cleanly separates orchestration, validation, and evaluation into isolated layers.

* **`registry.py`**: Discovers `.prompt-test.yaml` files, parses them via Pydantic (`test_case.py`), and builds a reverse index of dependencies.
* **`runner.py`**: Requests test execution from the `registry.py` and coordinates asynchronous execution via standard Python `asyncio`.
* **`engine.py` (Assertion Engine)**: Controlled by the runner, this orchestrates the sequence of assertions. It communicates with the `llm/factory.py` to dispatch LLM-as-judge calls dynamically depending on the current test model.
* **`llm/factory.py`**: Abstracts communication away from specific API clients (`anthropic_client.py` or `openai_client.py`), returning standardized data contracts regardless of provider.
* **`database.py` & `baseline_manager.py`**: Intervenes after `runner.py` completes executing tests. The baseline manager retrieves the latest historic passing baseline, performs the delta comparison (checking `test_results.json`), and commits to the database using `orm_models.py`.

---

## 🛠️ Tech Stack & Models Used

### Foundation & Web Layer
* **Language:** Python 3.11 (leveraging advanced `asyncio` for high concurrency)
* **API Framework:** FastAPI
* **CLI Engine:** Typer + Rich (Terminal output formatting)

### AI Evaluation & Embeddings
* **Evaluation Models:** Anthropic (Claude series) & OpenAI (GPT-4o) via official SDKs
* **Local Alternative:** `ollama` (via `httpx`) for zero-cost execution
* **Embeddings:** `all-MiniLM-L6-v2` via `sentence-transformers` for local, cost-free semantic assertions.

### Data Validation & Storage
* **Validation:** Pydantic v2
* **Database:** SQLite (Default for zero-setup local dev) → PostgreSQL (Ready for production scale via env change)
* **ORM:** SQLAlchemy 2.0 (Async enabled)
* **Dashboard Visualization:** Streamlit + Plotly

---

## 💻 System Requirements

* **Python:** 3.11+
* **Git:** Required for CI/CD test change detection.
* **LLM Access:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or local `ollama` instances.
* **Hardware Requirements:** A standard modern processor (No GPU required). Minimal storage (~80MB local disk space for embeddings).

---

## ⚙️ Configuration (.env)

The system is configured via environment variables. To get started, copy the configuration template:

```bash
cp .env.example .env
```
Inside your `.env`, you configure your API keys and (optionally) switch out your database provider.

```env
# Required for API LLM judging
ANTHROPIC_API_KEY=sk-ant-xxx...
OPENAI_API_KEY=sk-proj-xxx...

# Database Configuration (Defaults to local sqlite in dev)
# DATABASE_URL=postgresql+asyncpg://user:password@localhost/prs_db

# Tweaks for runner behavior
PRS_CONCURRENCY_LIMIT=10
```

---

## 🚀 Setup & Installation

### 1. Install Project Dependencies

```bash
git clone <repo_url>
cd prompt-regression-suite

# Set up virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Validate test cases safely
This parses the YAML files ensuring schema correctness without triggering API costs.
```bash
python cli.py validate
```

### 3. Run the complete suite locally
```bash
python cli.py run
```

### 4. Setting baselines (Initial run)
When testing a new prompt or accepting intentional prompt behavioral changes:
```bash
python cli.py run --update-baselines --commit-sha $(git rev-parse HEAD)
```

### 5. Launch web dashboards and Interfaces
```bash
# Launch Streamlit (http://localhost:8501)
streamlit run dashboard/app.py

# Launch FastAPI Swagger UI (http://localhost:8000/docs)
python cli.py serve --reload
```

---

## 📂 Folder Structure

```text
prompt-regression-suite/
├── src/
│   ├── config.py                 # Central pydantic settings
│   ├── registry.py               # YAML discovery & parsing logic
│   ├── runner.py                 # Async test coordination
│   ├── change_detector.py        # Identifies affected test logic based on git diffs
│   ├── models/                   # Pydantic schemas (test_case.py, result.py)
│   ├── llm/                      # API clients (Anthropic, OpenAI, Ollama)
│   ├── assertions/               # Tiered checking engine (Rule-based, Semantic, Judge)
│   ├── storage/                  # SQLite/PostgreSQL Database integrations
│   └── api/                      # FastAPI Routers
├── dashboard/
│   └── app.py                    # Visualizes regression trends in Streamlit
├── ci/                           # Scripts that run the GH Actions PR deployment gates
├── cli.py                        # Typer CLI definition file (`prs run`, etc)
├── prompts/                      # Example textual Prompt Templates
├── tests/                        # Source of truth (.prompt-test.yaml YAML tests)
└── .github/workflows/            # CI configurations for Weekly runs and PR blocking
```

---

## 💡 Real-World Use Cases

1. **Prompt Refactoring Safety Net:** Engineering successfully restructures a complex system prompt into cleaner subsections without risking "silent failures" in behavior.
2. **Model Version Drift Monitoring:** Setting up a weekly scheduled runner to detect if GPT-4 or Claude 3.5 quietly changes behavior across API updates, allowing proactive fixes.
3. **Structured Validation & Formatting:** Verify templates that are strictly required to return parsing-compliant JSON return exactly those keys every time.
4. **Tone Compliance Enforcement:** Blocking "unhelpful" or defensive phrasing generated in customer support ticketing bots.
5. **RAG Context Verification:** Assert that retrieved embedding chunks logically map correctly to the LLM's cited context inside generation cycles.
