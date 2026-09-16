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

The problem it addresses is that a call centre handles thousands of
conversations a day and remembers none of them: a customer quoted a price on
Monday is asked their room size, their budget and whether they have small
children all over again on Wednesday. This project treats that as a memory
problem rather than a model problem.

## Where to read more

| File | What it holds |
|---|---|
| [`docs/flow.md`](docs/flow.md) | The design, in 21 sections: the hot path, the cold path, the memory ledger, guardrails, handoff, evaluation and the improvement loop. Plus appendices on feature flags, cost and build order. |
| [`docs/diagrams.md`](docs/diagrams.md) | The same 21 subjects as figures. Section N of `docs/flow.md` explains figure N here. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How commits and branches are written, and the rules for changing the specification. |

`docs/flow.md` and `docs/diagrams.md` are the specification and they are binding. Changing
either is a decision, not an edit, and has its own rules — see
[CONTRIBUTING.md](CONTRIBUTING.md#changing-the-specification).

## Repository layout

```
docs/flow.md                     Specification: design intent, 21 sections
docs/diagrams.md                 Specification: 21 matching figures
CONTRIBUTING.md                  Commit, branch, specification and versioning conventions
LICENSE, NOTICE                  Apache License 2.0
.github/                         Pull request template
.gitattributes, .gitignore       Line endings, binary files, ignore rules
```

## Status

Specification and conventions only. No application code yet, no release tagged.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Built by Team 11 for the Sudo Code 2026 program.
