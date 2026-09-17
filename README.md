# Agent Core

> **The project has no final name yet.** "Agent Core" is a placeholder used in
> the badges, the licence and the documentation so that nothing has to stay
> blank. Renaming it later is a single `refactor` commit.

[![version](https://img.shields.io/badge/version-0.0.0-blue.svg)](CONTRIBUTING.md#versioning)

A customer-facing advisory agent for telesales that remembers. It talks to a
customer over chat, calls business tools for anything factual, and hands the
conversation to a human consultant when it reaches the edge of what it knows —
at which point it stays on as a copilot, drafting the human's replies and
checking them before they are sent.

The problem: a call centre handles thousands of conversations a day and
remembers none of them, so a customer quoted a price on Monday is asked their
room size, their budget and whether they have small children all over again on
Wednesday. This project treats that as a memory problem, not a model problem.

## Where to read more

| File | What it holds |
|---|---|
| [`docs/flow.md`](docs/flow.md) | The design, in 21 sections: hot path, cold path, memory ledger, guardrails, handoff, evaluation, improvement loop, plus appendices on feature flags, cost and build order |
| [`docs/diagrams.md`](docs/diagrams.md) | The same 21 subjects as figures. Section N of `docs/flow.md` explains figure N |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How commits and branches are written, and the rules for changing the specification |
| [`backend/reports/`](backend/reports) | Provider comparisons: latency, tokens and answers, one file per run |

`docs/flow.md` and `docs/diagrams.md` are the specification and they are
binding. Changing either is a decision, not an edit, and has its own rules —
see [CONTRIBUTING.md](CONTRIBUTING.md#changing-the-specification).

## Project structure

Two deployments, kept apart. The API runs on Azure App Service; the browser app
is built and hosted separately, so every call between them is cross-origin and
CORS is configured rather than avoided.

```
backend/
  config/
    models.yaml               Providers, models, rate limits, agent routing
    probe_prompts.yaml        Trial prompts for the provider comparison
  src/
    config/config_manager.py  Loads .env once, parses the YAML, fails fast
    llm/                      Factory, rate limiter, token ledger, tracing
    agents/                   Agent base, and the advisor on top of it
    api/                      FastAPI: settings, db, auth, chat
  examples/probe_providers.py Compare providers: list, run, limits
  reports/                    Run reports, newest first, older under archive/
  tests/
  setup.py                    Preflight check, run this first
  startup.sh                  Azure App Service startup command
  requirements.txt
  .env.example
frontend/
  src/
    services/                 API client, SSE reader, token storage
    context/AuthContext.jsx   Who is signed in
    pages/                    Login, Chat
    components/               Sidebar, message bubble, composer
  package.json
  .env.example
docs/                         The specification
```

## Getting started

### Backend

```sh
cd backend
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then fill it in
python setup.py                                       # says what is still missing
uvicorn src.api.app:app --reload
```

`setup.py` checks the interpreter, the packages, and every variable the service
needs, and prints the steps still left rather than failing halfway through a
request.

### Frontend

```sh
cd frontend
npm ci
cp .env.example .env     # leave VITE_API_BASE_URL blank for local work
npm run dev
```

Left blank, the dev server proxies `/api` to `http://127.0.0.1:8000`, so local
development never touches CORS. Set `VITE_API_BASE_URL` to the deployed API
origin for a real build, and add that page's origin to `CORS_ORIGINS` on the
server — the browser refuses the call otherwise, before it leaves.

### Comparing providers

```sh
cd backend
python examples/probe_providers.py list    # which models your keys can reach
python examples/probe_providers.py run     # score, time, and save a report
```

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

```sh
cd backend && python -m pytest
```

Adding a provider is a config change plus one package: `init_chat_model`
dispatches on the provider id, so there is no branch in the factory to edit.

Rate limiting counts an attempt when the call is made, not when it succeeds. A
limiter that only counts successes stops counting exactly when a provider
starts failing, and the retry loop becomes a flood; `tests/test_rate_limiter.py`
holds that behaviour in place.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Built by Team 11 for the Sudo Code 2026 program.
