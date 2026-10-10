# Agent Core

> **Evaluation.** One command, `backend/.venv/bin/python evaluation/run_eval.py evaluate`,
> runs the agent through [`evaluation/`](evaluation/README.md) and writes the run to
> `evaluation/runs/<date-time>/`; the table is `scored/scorer.stdout.txt`.
> What each folder holds: [section 5](#5-evaluation).

> **The project has no final name yet.** "Agent Core" is a placeholder used in
> the badges, the licence and the documentation so that nothing has to stay
> blank. Renaming it later is a single `refactor` commit.

[![version](https://img.shields.io/badge/version-0.0.0-blue.svg)](CONTRIBUTING.md#versioning)

A customer-facing advisory agent for telesales that remembers. It talks to a
customer over the shop's web chat, Zalo or a spoken hotline call, calls
business tools for anything factual, and hands the conversation to a human
consultant when it reaches the edge of what it knows — at which point it stays
on as a copilot, drafting the human's replies and checking them before they
are sent.

The problem: a call centre handles thousands of conversations a day and
remembers none of them, so a customer quoted a price on Monday is asked their
room size, their budget and whether they have small children all over again on
Wednesday. This project treats that as a memory problem, not a model problem.

## Where to read more

| File | What it holds |
|---|---|
| [`docs/design.md`](docs/design.md) | The design, text and figures in one place: figure 1 follows one call from advice to improvement, and nine component figures (intake, identity, memory, tools, knowledge base, guardrails, handoff, evaluation, self-reflection) sit in the sections they illustrate. Appendices cover the organisers' grading contract, models, cache and open questions |
| [`docs/figures/`](docs/figures) | The figures: `design.excalidraw` is the single source, and each SVG is one figure cut from it |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How commits and branches are written, and the rules for changing the specification |

`docs/design.md` is the specification and it is binding. Changing it, text or
figure, is a decision, not an edit, and has its own rules — see
[CONTRIBUTING.md](CONTRIBUTING.md#changing-the-specification).

## Project structure

Two deployments, kept apart. The API runs on Azure App Service; the browser app
is built and hosted separately, so every call between them is cross-origin and
CORS is configured rather than avoided.

```
backend/
  config/
    models.yaml               Providers, models, rate limits, agent routing, voice models
    lanes.yaml                Which tools the advisor may see in each lane
  src/
    config/config_manager.py  Loads .env once, parses the YAML, fails fast
    llm/                      Factory, rate limiter, token ledger, tracing, Jev client
    components/               One package per function: intake, identity, memory,
                              orchestration, context, guardrails, handoff, voice,
                              evaluation
    agents/                   Advisor, Policy, Memory, QA; none holds state
    pipeline/                 hot/: the seven-node graph of one turn; cold/: after the call;
                              eval/: the agent as the evaluation drives it
    mcp/                      Server skeleton, client per role, and the five servers
    api/                      FastAPI: calls (chat over SSE), voice (WebSocket), admin
  lab/                        Where design ideas are tried before they reach src/ (voice, Jev)
  docker-compose.yml          The Postgres the API needs
  setup.py                    Preflight check, run this first
  requirements.txt
  .env.example
frontend/
  src/
    services/                 API client, SSE reader, token and session storage
    context/AuthContext.jsx   Who is signed in, and as what role
    pages/                    Chat for customers; console and the rest for staff
    components/               Shell, message bubble, composer, charts
  package.json
  .env.example
evaluation/
  run_eval.py                 The evaluation in one command (Getting started, section 5)
  product.py                  Prepares a run of the agent and runs every stage
  eval_harness/               Pinning, running, collecting and scoring
  datasets/                   The diagnostic scenarios
  evaluation-contracts/       Schemas, fixtures and the organisers' sources the harness pins
docs/
  design.md                   The specification
  figures/                    Its figures: one Excalidraw source and the SVGs cut from it
```

## Getting started

Running the project on your own machine. The backend and the frontend each run
in their own terminal, both started from the repository root.

### Requirements

| Tool | Version | Used for |
|---|---|---|
| Python | 3.12 (3.10 is the minimum) | Backend |
| Node.js | 22.12 or newer, or 20.19 or newer | Frontend |
| Docker | With Compose v2 | PostgreSQL 16 with pgvector |

### 1. Backend

Start the database and create the environment:

```sh
cd backend
docker compose up -d
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

On Windows, create the environment with `py -3.12 -m venv .venv` and activate it
with `.venv\Scripts\activate`.

Open `.env` and fill in:

| Variable | Value |
|---|---|
| `GOOGLE_API_KEY` | Gemini key. The advisor runs on it. `GROQ_API_KEY` and `NVIDIA_API_KEY` add their models to the Admin page's choices |
| `AI_GATEWAY_API_KEY` | Optional. Vercel AI Gateway key for the PolicyAgent's model, Jev. Without it the soft policy check is skipped and the hard check alone guards replies |
| `DATABASE_URL` | `postgresql://postgres:dev@127.0.0.1:55432/agentcore` |
| `JWT_SECRET` | The output of `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SEED_USER_EMAIL`, `SEED_USER_PASSWORD` | The staff account. There is no registration page |
| `SEED_CUSTOMER_EMAIL`, `SEED_CUSTOMER_PASSWORD` | Optional customer account, for trying the chat |
| `CORS_ORIGINS` | `http://localhost:5173` |

The catalogue, CRM, promotions and policy documents are the organisers'
data, committed in `backend/data/btc`. `BTC_DATA_DIR` in `.env` points at a
newer copy without editing the repository.

Check the setup, then start the API:

```sh
python setup.py
uvicorn src.api.app:app --reload
```

`setup.py` lists anything still missing. The API listens on
`http://127.0.0.1:8000`.

### 2. Frontend

In a second terminal:

```sh
cd frontend
npm ci
cp .env.example .env
npm run dev
```

The app is served at `http://localhost:5173`. Leave `VITE_API_BASE_URL` blank in
`frontend/.env`: the dev server forwards `/api` to the backend on port 8000.

### 3. Sign in

Open `http://localhost:5173` and sign in with the account from `.env`. The staff
account opens the console; the customer account chooses how to reach the shop:
the web chat, a Zalo conversation, or a call to the hotline. Nothing else
needs to be launched, because the API starts the five MCP servers itself.
`http://127.0.0.1:8000/health` reports the state of the service.

### 4. Voice

The hotline channel hears and speaks on the server itself, on CPU. Its
packages come with `requirements.txt`. Its model weights, about 2.5 GB with
the voice, download in the background the first time the API starts, and are
loaded before the first call; until then the call page says voice is not ready.
To fetch them ahead of time:

```sh
cd backend
python -m src.components.voice.fetch
```

The recogniser, the end-of-turn detection, the cut-in threshold and the voice
are chosen on the Admin page.

### 5. Evaluation

One place, one command. The evaluation lives in `evaluation/`: the
scenarios (`datasets/output1-btc-diagnostic-v1`, five generated multi-call
scenarios whose labels await QA), a grading contract per scenario, a schema
check on every piece of evidence, the organisers' grader and checks of its
own. It runs the agent in `backend/`, the same graph, agents and memory the
API serves, once with memory and once without. Postgres must be up; the API
need not be running.

```sh
backend/.venv/bin/python evaluation/run_eval.py evaluate
```

`--only SCENARIO_ID` runs one scenario (repeat it for more), and
`--out <dir>` names the run directory. Without `--out` the run goes to
`evaluation/runs/<date-time>/`, one folder per stage, none overwritten:

| Folder | Stage | Read first |
|---|---|---|
| `inputs/` | the pinned scenarios, grading contracts, manifest and adapter | `preparation-report.json` |
| `raw/` | the agent's hooks and every tool event, per configuration | `runner-report.json`, `full/adapter-0.log` |
| `evidence/` | transcripts, extraction, memory, briefs, and the trace in the organisers' format | `full.jsonl`, `baseline.jsonl`, `validation.json` |
| `scored/` | the organisers' grader and the harness's own checks | `scorer.stdout.txt` (the table), `official-report.json`, `supplemental-report.json`, `validation.json` |

`execution-report.json` at the top of the run sums up every stage, and the
command prints the table at the end. The exit code is 0 for a complete pass,
1 when a check failed, 2 when evidence is incomplete, 3 when the run could
not be carried out.

How it reaches the agent: the harness's adapter (`evaluation/product_adapter.py`)
starts `backend/src/pipeline/eval/bridge.py` in a process of its own. Every
business tool the agent calls comes back to the harness's copy of the
organisers' mock, which records the call and the state it changed; memory
and knowledge stay on the agent's MCP servers, in a database of its own
(`agentcore_eval`, emptied before each scenario). Nothing is retried. Each
turn is labelled by `backend/src/pipeline/eval/extract_command.py` with the
harness's prompt.

Runs are not committed: a single scenario already writes about 3 MB, most of
it copies of the organisers' data that each stage pins. Latency measured on a
free Gemini key includes the waits its rate limit imposes.

## Configuration

Two layers, kept apart so that secrets never reach version control.

- **`config/*.yaml`** is committed and holds no secrets. There are no `${VAR}`
  placeholders in it and nothing expands them, so a missing value cannot turn
  into a silent `None`.
- **`.env`** holds the keys. It is loaded once, in
  `src/config/config_manager.py`, and each LangChain integration reads its own
  variable from the environment. Variables already set in the environment win,
  so an IDE run configuration or CI can override the file without editing it.

Asking for a provider whose key is absent raises immediately, naming the
variable.

## Development

`backend/lab/` is where a design idea is tried before it reaches `src/`: the
voice bench that compared recognisers and voices, and the Jev bench. Tests and
run reports live in `backend/workbench/`, which each clone keeps for itself
and never pushes. With it in place:

```sh
cd backend
python -m pytest workbench/tests
```

Adding a provider is a config change plus one package: `init_chat_model`
dispatches on the provider id, so there is no branch in the factory to edit.

Rate limiting counts an attempt when the call is made, not when it succeeds. A
limiter that only counts successes stops counting exactly when a provider
starts failing, and the retry loop becomes a flood. The rate limiter's tests hold
that behaviour in place.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Built by Team 11 for the Sudo Code 2026 program.
