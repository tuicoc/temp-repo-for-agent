# Contributing

This file is the project's working agreement. It describes how commits are
written, how branches are named, and how the specification is changed.

Nothing here is checked by a tool. We hold each other to it, and a pull request
needs a reviewer's approval before it can be merged — that review is where the
agreement is actually applied.

Everything written into the repository — commit messages, branch names, pull
request titles, code comments, documentation — is in English. Conversation
between us is not.

---

## Commit messages

The format is [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).

```
<type>(<scope>)!: <subject>

<body>

<footer>
```

- **type** — required, from the table below.
- **scope** — optional but expected, from the scope list below. Lowercase.
- **!** — marks a breaking change. Also requires a `BREAKING CHANGE:` footer
  explaining what breaks and what to do about it.
- **subject** — required, imperative mood ("add", not "added" or "adds"), no
  trailing period, at most 65 characters.
- **body** — separated by one blank line. Required for anything whose reason is
  not obvious from the subject. Explain *why*, not *what*; the diff already says
  what.
- **footer** — `BREAKING CHANGE: …`, `Refs: #42`, `Closes: #42`.

### Types

| Type | Use it for | Version effect |
|---|---|---|
| `feat` | a new capability of the product | MINOR |
| `fix` | a defect corrected | PATCH |
| `spec` | a change to `docs/design.md` or its figures in `docs/figures/` — see below | PATCH |
| `perf` | a change that only makes something faster or cheaper | PATCH |
| `refactor` | restructuring with no change in behaviour | PATCH |
| `docs` | documentation other than the specification | none |
| `build` | dependencies, packaging, Docker, Makefile | none |
| `ci` | pipeline configuration | none |
| `test` | tests only | none |
| `style` | formatting with no change in meaning | none |
| `chore` | housekeeping that fits nothing above | none |
| `revert` | reverting an earlier commit | none |

Before reaching for `chore`, check the table again. `chore` is where intent goes
to die, and a history full of it is the failure mode this document exists to
prevent.

### Scopes

Scopes come from the components in `docs/design.md`, so a scope is always a real part
of the system rather than a folder name that will move:

| Layer | Scopes |
|---|---|
| Harness (the seven-node turn) | `harness`, `route`, `advisor`, `context`, `guard`, `fallback` |
| Intake (figure A) | `ingest`, `asr`, `itn`, `pii`, `voice` |
| Identity (figure B) | `identity` |
| Memory (figure C) | `memory`, `ontology`, `brief` |
| Tools (figure D) | `mcp`, `catalog`, `crm`, `order` |
| Knowledge base (figure E) | `knowledge` |
| Handoff (figure G) | `handoff`, `copilot` |
| Evaluation (figure H) | `eval`, `scorer`, `manifest`, `simulator` |
| Improvement (figures G and I) | `improve`, `faq`, `reflection`, `playbook` |
| Interface | `ui`, `console` |
| Cross-cutting | `api`, `db`, `config`, `llm`, `trace`, `policy`, `qa` |
| Specification | `design` |

Add a scope by adding it here in the same commit that first uses it.

### Examples

```
feat(advisor): bind tools by lane instead of binding all of them

The out-of-scope lane must be able to assert that no tool was called, which
is only mechanically true if the lane binds an empty tool list.

Refs: #31
```

```
fix(guard): reject a price that is absent from this turn's tool results

Vietnamese money is written several ways (4.890.000d, 4tr890, 4,89 trieu),
and the previous pattern matched only the first. A quote the model invented
in the second form passed the check.
```

```
spec(design)!: merge section 4.10 into section 4.9

Handoff and fallback share one mechanism, so describing them apart invited
two implementations. Figure G is redrawn to show both.

BREAKING CHANGE: sections after 4.9 are renumbered. Any document or issue
citing "section 4.11" now means section 4.10.
```

---

## Changing the specification

`docs/design.md` is the specification, and its figures are part of it. It is
not a set of notes. Every other file in this repository exists to implement it,
so a change to it is a change to what the project has committed to build.

The figures are drawn in Excalidraw. All of them live in one source file,
`docs/figures/design.excalidraw`; each figure in `design.md` is an SVG cut from
that file, with a fixed name (`1-flow.svg`, `a-intake.svg` … `i-reflection.svg`).
To change a figure, open the source on [excalidraw.com](https://excalidraw.com)
or in an Excalidraw editor plugin, edit it, select the elements of the figure
you changed, export them as SVG with **Only selected** ticked, and save over the
file of the same name.

Four rules:

**1. Use the `spec` type.** Not `docs`. A change to the specification is then
findable with `git log --grep '^spec'`. The scope is `design`.

**2. Change the text and the figure together.** A figure and the paragraph that
explains it are one statement. A commit that changes a figure without its text,
or the text without its figure, leaves the specification saying two things, so
the reviewer sends it back. Commit the source file and the exported SVGs in the
same commit.

**3. State the reason in the body.** A specification change is a decision. The
body records what was decided and why, because in four weeks nobody will
remember, and the defence will ask.

| Change | How to write it |
|---|---|
| Add a section | `spec(design): add section 14 on rate limiting`. If it needs a figure, draw it in the same source file and export it in the same commit. |
| Edit a section | `spec(design): …` with a body naming the section and the reason. |
| Remove a section | `spec(design)!: …` with a `BREAKING CHANGE:` footer. Removal renumbers everything after it, which invalidates every outside reference. |
| Renumber | Always breaking. Same rule as removal. |

**4. One decision per commit.** Do not bundle a specification change with the
code that implements it. The specification is the thing being agreed; the code
is the consequence. Separate commits keep the decision reviewable on its own,
and keep `git log --grep '^spec'` a readable history of what the project decided.

---

## Branches

The format is [Conventional Branch](https://conventionalbranch.org):
`<type>/<short-description>`.

| Prefix | For |
|---|---|
| `feature/` | a new capability |
| `bugfix/` | a defect on `main` |
| `hotfix/` | an urgent fix that cannot wait for the normal cycle |
| `spec/` | a change to `docs/design.md` or its figures |
| `docs/` | documentation other than the specification |
| `refactor/`, `test/`, `perf/`, `build/`, `ci/`, `chore/` | as the matching commit type |
| `release/` | release preparation; the only prefix allowed to contain dots |
| `ai/`, `claude/` | work driven by an AI coding agent |

The description uses lowercase letters, digits, and single hyphens. It may carry
a tracker id. Only a release branch may contain dots, and only as a version.

```
feature/call-brief-renderer
bugfix/issue-42-expired-quote-price
spec/merge-handoff-into-section-12
release/0.2.0
```

`main` needs no prefix and is the only long-lived branch. Branch from `main`,
merge back into `main`, delete the branch.

---

## Pull requests

- The title follows the same schema as a commit message. On a squash merge the
  title becomes the subject on `main`, so it is the message that survives.
- One concern per pull request. A specification change and its implementation
  are two pull requests.
- At least one reviewer must approve before merging. This is the project's only
  enforced rule; everything else above is upheld by that review.
- Delete the branch after merging.

The approval requirement is a repository setting, not a file. Enable it once, on
GitHub, under **Settings → Branches → Add branch ruleset**: target `main`, then
tick **Require a pull request before merging** with **Required approvals: 1**.

---

## Versioning

[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). While the major
version is `0` the interface is unstable by definition, so a breaking change
moves the minor digit rather than the major one.

A release is a git tag, `v0.1.0`. Two files carry the version badge and both
are updated in the same commit: `README.md` and `docs/design.md`.
The specification is versioned with the project rather than on its own, so
there is one number to quote and no chance of the two disagreeing.

Nothing is released yet; the version is `0.0.0`.
