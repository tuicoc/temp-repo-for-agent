# Jev lab

Should an evaluation model (Jev, through Vercel AI Gateway) replace a chat
model for the agent's typed decisions? Five tasks from `docs/flow.md`, the same
typed questions put to Jev, Gemini 3.5 Flash-Lite and GPT-OSS 20B on Groq,
scored against hand labels and timed per call. The code is committed as a
record of the experiment; results and the report stay in the local
`workbench/reports/jev/`.

| Task | Data | What is scored |
|---|---|---|
| Routing (section 9) | `data/route.jsonl`, 40 turns | intent, asks for a person, needs a tool |
| Identity confirmation (section 5) | `data/identity.jsonl`, 16 answers | confirms or not |
| Policy check (section 11.2) | `data/policy.jsonl`, 30 drafts | six violation kinds; block or pass per draft |
| FAQ rerank (section 8.1, `ff.kb_rag`) | `data/faq.json`, `data/faq_queries.jsonl` | top passage; out of scope; BM25 as the free baseline |
| Repeat-question scorer (Appendix A.1) | `data/rqr.jsonl`, 20 questions | asks a known fact again or not |

Every case is meant to be hard: negations, teencode, no diacritics, staff
mentioned without asking for one, arithmetic and date comparisons the policy
hides, near-duplicate FAQ entries.

## Run

Needs `AI_GATEWAY_API_KEY`, `GOOGLE_API_KEY` and `GROQ_API_KEY` in
`backend/.env`, and a card on the Vercel team.

```
cd backend
.venv/bin/python lab/jev/run.py
.venv/bin/python lab/jev/report.py
```

`run.py` appends every answer to `cache.jsonl` as it arrives, so a stopped run
resumes and `--score` rescores without a call. `report.py` writes
`workbench/reports/jev/jev-bench.html`, with the judgement per task taken from
`verdict.json`.

| File | Part |
|---|---|
| `tasks.py` | Questions in English and Vietnamese, state per item |
| `run.py` | Backends, cache, timing, scoring, `results.json` |
| `report.py` | The page |
| `verdict.json` | The recommendation per task, written after reading the numbers |
| `NOTES.md` | Settings that worked, setup done, where the trial was paused (Vietnamese) |
