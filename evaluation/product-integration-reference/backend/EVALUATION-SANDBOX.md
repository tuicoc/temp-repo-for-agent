# PostgreSQL evaluation sandbox

Separate Compose project `agent-evaluation`, database `agent_eval_dev`, bound only to
`127.0.0.1:55433`. Does not modify the existing `agent-core` project or production DB.
Docker Desktop must be running. The setup script uses the installed backend environment.

From this backend directory:

```sh
.venv/bin/python -B setup_evaluation_db.py --test --test-adapter
```

This starts PostgreSQL and verifies persistence after reconnect, namespace separation,
web start/turn/end using fake models, and P2/P3/P4 adapter behavior.
Password is generated on first setup and recovered from the existing sandbox container on
later runs; never printed or copied into reports. The named volume keeps memory across
container restarts. Do not use `down -v` or delete the sandbox container/volume to fix errors.
If the volume survives but its container is missing, setup stops for credential recovery.

The adapter check runs actual PostgreSQL with offline Memory/Advisor graphs through
P2/P3/P4; no paid model calls. Prepare CLI defaults to PostgreSQL; its DSN must be in
EVALUATION_DATABASE_URL (credentials never included in the bundle). Missing DSN is an
error, never an automatic SQLite fallback. sqlite_unit is only for component diagnostics.
This does not start the web application or migrate production. For an explicitly local
UI smoke, run `backend/.venv/bin/python -B backend/setup_evaluation_db.py --serve` from
the workspace root. The launcher overrides `DATABASE_URL` only in the child process to
the isolated sandbox DB; it never reads/uses the app `.env` database URL. The app's auth
tables and demo seed account are created only inside this same sandbox database. The web
call feature flag stays off by default everywhere else. The UI should use synthetic BTC
phone numbers/data only; each call has a hard cap of 12 model attempts. With the web-call
feature flag enabled, legacy `/api/conversations` messages use the same `CallRuntime` and
the app conversation records only masked checked text. Calls have durable status/evidence;
after backend restart an interrupted OPEN call requires QA reconciliation, and unknown tool
outcomes cannot be automatically reconciled or retried. Active graphs remain process-local:
do not run multi-worker. The QA-only rule producer derives deduplicated signals from committed
turns/tool events; its R0/R1 paired-run endpoint can call the real model and must only be
invoked with a separately approved API budget. Its comparison is diagnostic, always hold,
not a quality score or release. A store/adapter test passing is not an M1 functional or
acceptance PASS.

Google credentials belong in `backend/.env` or the process environment, not Compose YAML,
source snapshots, Git, reports or chat. An `export` in a separate terminal does not update
an already-running Codex/backend process. Every real model run needs its own approved budget.
