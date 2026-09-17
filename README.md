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
| [`reports/`](reports) | Provider comparisons: latency, tokens and answers, one file per run |

`docs/flow.md` and `docs/diagrams.md` are the specification and they are
binding. Changing either is a decision, not an edit, and has its own rules —
see [CONTRIBUTING.md](CONTRIBUTING.md#changing-the-specification).

## Project structure

```
config/                       Configuration, no secrets
  models.yaml                 Providers, models, rate limits
  probe_prompts.yaml          Trial prompts for the provider comparison
src/
  config/
    config_manager.py         Loads .env once, parses the YAML, fails fast
  llm/
    factory.py                LLMFactory: builds a chat model from a config block
    rate_limiter.py           Sliding-window request and token limiting
    callback_handler.py       Token accounting, rate-limit backoff
    token_ledger.py           Per-agent token totals for one run
    tracing.py                Langfuse, optional, with PII masking
  report.py                   Writes run reports as JSON and Markdown
examples/
  probe_providers.py          Compare providers: list, run, limits
tests/                        Unit tests
docs/                         The specification
reports/                      Output of each comparison run
setup.py                      Preflight check, run this first
requirements.txt              Direct dependencies, pinned
```

## Getting started

**1. Create and activate a virtual environment.** Python 3.10 or newer; 3.12 is
what this was developed against.

```sh
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

**2. Install the dependencies.**

```sh
pip install -r requirements.txt
```

**3. Add your API keys.** Copy the template and fill it in. `.env` is
git-ignored; never put a real key in `.env.example`.

```sh
cp .env.example .env
```

| Variable | Where to get it | Required |
|---|---|---|
| `GOOGLE_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | yes |
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) | yes |
| `NVIDIA_API_KEY` | [build.nvidia.com](https://build.nvidia.com) | yes |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | [cloud.langfuse.com](https://cloud.langfuse.com) | no, tracing only |

**4. Check the machine is ready.** This reports what is still missing and what
to do about it, rather than failing halfway through a run.

```sh
python setup.py
```

**5. Compare the providers.**

```sh
python examples/probe_providers.py list    # which models your keys can reach
python examples/probe_providers.py run     # latency, tokens and answers
```

`run` writes a timestamped report to `reports/`, with charts, so runs can be
compared over time.

To measure a rate limit rather than trust a published figure:

```sh
python examples/probe_providers.py limits --provider groq --model openai/gpt-oss-20b
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
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
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
