"""Namespace-scoped sandbox persistence; never falls back to DATABASE_URL."""
import json
import sqlite3
import threading
from contextlib import contextmanager


class RuntimeStore:
    def __init__(self, namespace, dsn=None):
        if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 512:
            raise ValueError("Explicit bounded namespace required")
        self.namespace = namespace
        self._job_lock = threading.RLock()
        self.postgres = dsn is not None
        if self.postgres:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict
            settings = conninfo_to_dict(dsn)
            if settings.get("host") not in ("127.0.0.1", "localhost", "::1") or settings.get("dbname") != "agent_eval_dev" or settings.get("port") != "55433":
                raise ValueError("Only explicitly configured local evaluation DB is allowed")
            self.db = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
        else:
            self.db = sqlite3.connect(":memory:")
        with self.transaction():
            if self.postgres:
                self.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", ("agent-evaluation/runtime-migrations/v1",))
            for table, columns in (
                ("runtime_migrations", "version INTEGER PRIMARY KEY"),
                ("customers", "namespace TEXT, customer TEXT, payload TEXT, PRIMARY KEY(namespace,customer)"),
                ("facts", "namespace TEXT, customer TEXT, slot TEXT, payload TEXT, PRIMARY KEY(namespace,customer,slot)"),
                ("sessions", "namespace TEXT, customer TEXT, call TEXT, payload TEXT, PRIMARY KEY(namespace,customer,call)"),
                ("fact_events", "namespace TEXT, customer TEXT, slot TEXT, payload TEXT"),
                ("business_events", "namespace TEXT, customer TEXT, call TEXT, turn INTEGER, event_index INTEGER, payload TEXT, PRIMARY KEY(namespace,customer,call,turn,event_index)"),
                ("gap_candidates", "namespace TEXT, candidate_id TEXT, question_norm TEXT, intent TEXT, payload TEXT, content_hash TEXT, status TEXT, PRIMARY KEY(namespace,candidate_id), UNIQUE(namespace,question_norm,intent)"),
                ("gap_events", "namespace TEXT, event_id TEXT, candidate_id TEXT, payload TEXT, PRIMARY KEY(namespace,event_id)"),
                ("calls", "namespace TEXT, customer TEXT, call TEXT, status TEXT, payload TEXT, PRIMARY KEY(namespace,customer,call)"),
                ("turns", "namespace TEXT, customer TEXT, call TEXT, turn INTEGER, payload TEXT, PRIMARY KEY(namespace,customer,call,turn)"),
                ("jobs", "namespace TEXT, customer TEXT, call TEXT, kind TEXT, status TEXT, payload TEXT, PRIMARY KEY(namespace,customer,call,kind)"),
                ("qa_reviews", "namespace TEXT, customer TEXT, call TEXT, criterion_id TEXT, payload TEXT, PRIMARY KEY(namespace,customer,call,criterion_id)"),
                ("model_attempts", "namespace TEXT, customer TEXT, call TEXT, attempts INTEGER NOT NULL, PRIMARY KEY(namespace,customer,call)"),
                ("web_calls", "call_id TEXT PRIMARY KEY, namespace TEXT, owner TEXT, customer TEXT, call TEXT, conversation_id INTEGER, status TEXT, payload TEXT"),
                ("gap_comparisons", "comparison_id TEXT PRIMARY KEY, namespace TEXT, payload TEXT"),
            ):
                self.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
            self.execute("INSERT INTO runtime_migrations VALUES (1) ON CONFLICT(version) DO NOTHING")
            self.execute("INSERT INTO runtime_migrations VALUES (2) ON CONFLICT(version) DO NOTHING")
            self.execute("INSERT INTO runtime_migrations VALUES (3) ON CONFLICT(version) DO NOTHING")
            self.execute("INSERT INTO runtime_migrations VALUES (4) ON CONFLICT(version) DO NOTHING")
            self.execute("INSERT INTO runtime_migrations VALUES (5) ON CONFLICT(version) DO NOTHING")
            self.execute("INSERT INTO runtime_migrations VALUES (6) ON CONFLICT(version) DO NOTHING")
            self.execute("INSERT INTO runtime_migrations VALUES (7) ON CONFLICT(version) DO NOTHING")
            self.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_open_web_conversation ON web_calls(owner,conversation_id) WHERE conversation_id IS NOT NULL AND status IN ('OPEN','RECONCILIATION_REQUIRED')")

    def write_turn(self, customer, call, turn, payload):
        with self.transaction():
            self.execute("INSERT INTO turns VALUES(?,?,?,?,?)", (self.namespace, customer, call, turn, json.dumps(payload, ensure_ascii=False, allow_nan=False)))

    def enqueue_job(self, customer, call, kind):
        with self.transaction():
            self.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,customer,call,kind) DO NOTHING",
                         (self.namespace, customer, call, kind, "PENDING", "{}"))

    def job_status(self, customer, call, kind):
        row=self.execute("SELECT status FROM jobs WHERE namespace=? AND customer=? AND call=? AND kind=?",
                         (self.namespace,customer,call,kind)).fetchone()
        return row[0] if row else None

    def claim_job(self, customer, call, kind):
        with self.transaction():
            updated=self.execute("UPDATE jobs SET status='RUNNING' WHERE namespace=? AND customer=? AND call=? AND kind=? AND status='PENDING'",
                                 (self.namespace,customer,call,kind))
            return updated.rowcount==1

    def model_attempt_count(self, customer, call):
        row=self.execute("SELECT attempts FROM model_attempts WHERE namespace=? AND customer=? AND call=?",
                         (self.namespace,customer,call)).fetchone()
        return row[0] if row else 0

    def initialize_model_budget(self, customer, call):
        with self.transaction():
            self.execute("INSERT INTO model_attempts VALUES(?,?,?,0) ON CONFLICT(namespace,customer,call) DO NOTHING",
                         (self.namespace,customer,call))

    def has_model_budget(self, customer, call):
        return self.execute("SELECT 1 FROM model_attempts WHERE namespace=? AND customer=? AND call=?",
                            (self.namespace,customer,call)).fetchone() is not None

    def recoverable_web_jobs(self, limit=10):
        if not self.postgres or type(limit) is not int or not 1<=limit<=100:
            raise ValueError("Web recovery requires bounded sandbox PostgreSQL query")
        rows=self.execute("SELECT j.namespace,j.customer,j.call FROM jobs j JOIN calls c ON c.namespace=j.namespace AND c.customer=j.customer AND c.call=j.call "
                          "WHERE j.namespace LIKE 'web-demo/%' AND j.kind='persist' AND j.status IN ('PENDING','RUNNING') "
                          "AND c.status IN ('OPEN','FINALIZING') ORDER BY j.namespace,j.call LIMIT ?",(limit,)).fetchall()
        return [{"namespace":row[0],"customer":row[1],"call":row[2]} for row in rows]

    def claim_model_attempt(self, customer, call, limit):
        if type(limit) is not int or limit<1:
            raise ValueError("Explicit positive model-attempt limit required")
        with self.transaction():
            self.execute("INSERT INTO model_attempts VALUES(?,?,?,0) ON CONFLICT(namespace,customer,call) DO NOTHING",
                         (self.namespace,customer,call))
            updated=self.execute("UPDATE model_attempts SET attempts=attempts+1 WHERE namespace=? AND customer=? AND call=? AND attempts<?",
                                 (self.namespace,customer,call,limit))
            if updated.rowcount!=1:
                raise RuntimeError("Pinned model-call budget exhausted")
            return self.model_attempt_count(customer,call)

    @contextmanager
    def job_lock(self, customer, call, kind):
        key=f"{self.namespace}/{customer}/{call}/{kind}"
        with self._job_lock:
            if self.postgres and not self.execute("SELECT pg_try_advisory_lock(hashtextextended(?,0))",(key,)).fetchone()[0]:
                raise RuntimeError("After-call job is already running")
            try:
                yield
            finally:
                if self.postgres:
                    self.execute("SELECT pg_advisory_unlock(hashtextextended(?,0))",(key,))

    def set_job_status(self, customer, call, kind, status):
        if status not in ("RUNNING","COMPLETED","FAILED"):
            raise ValueError("Invalid job status")
        with self.transaction():
            self.execute("UPDATE jobs SET status=? WHERE namespace=? AND customer=? AND call=? AND kind=?",
                         (status,self.namespace,customer,call,kind))

    def save_qa_review(self, customer, call, criterion_id, result):
        with self.transaction():
            self.execute("INSERT INTO qa_reviews VALUES(?,?,?,?,?) ON CONFLICT(namespace,customer,call,criterion_id) DO NOTHING",
                         (self.namespace,customer,call,criterion_id,json.dumps(result,ensure_ascii=False,allow_nan=False)))

    def qa_reviews(self, customer, call):
        return [json.loads(row[0]) for row in self.execute(
            "SELECT payload FROM qa_reviews WHERE namespace=? AND customer=? AND call=? ORDER BY criterion_id",
            (self.namespace,customer,call))]

    def write_business_event(self,customer,call,turn,event_index,payload):
        self.execute("INSERT INTO business_events VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,customer,call,turn,event_index) DO UPDATE SET payload=excluded.payload",
                     (self.namespace,customer,call,turn,event_index,json.dumps(payload,ensure_ascii=False,allow_nan=False)))

    def business_events(self,customer,call=None):
        if call is None:
            rows=self.execute("SELECT payload FROM business_events WHERE namespace=? AND customer=? ORDER BY call,turn,event_index",(self.namespace,customer))
        else:
            rows=self.execute("SELECT payload FROM business_events WHERE namespace=? AND customer=? AND call=? ORDER BY turn,event_index",(self.namespace,customer,call))
        return [json.loads(row[0]) for row in rows]

    def list_gap_candidates(self):
        return [json.loads(row[0]) for row in self.execute("SELECT payload FROM gap_candidates WHERE namespace=? ORDER BY candidate_id",(self.namespace,))]

    def get_gap_candidate(self,candidate_id):
        row=self.execute("SELECT payload FROM gap_candidates WHERE namespace=? AND candidate_id=?",(self.namespace,candidate_id)).fetchone()
        return json.loads(row[0]) if row else None

    def save_gap_candidate(self,candidate):
        self.execute("INSERT INTO gap_candidates VALUES(?,?,?,?,?,?,?) ON CONFLICT(namespace,candidate_id) DO UPDATE SET question_norm=excluded.question_norm,intent=excluded.intent,payload=excluded.payload,content_hash=excluded.content_hash,status=excluded.status",
                     (self.namespace,candidate["candidate_id"],candidate["question_norm"],candidate["intent"],json.dumps(candidate,ensure_ascii=False,allow_nan=False),candidate["content_hash"],candidate["status"]))

    def append_gap_event(self,event_id,candidate_id,payload):
        from datetime import datetime,timezone
        payload={**payload,"at":payload.get("at",datetime.now(timezone.utc).isoformat())}
        self.execute("INSERT INTO gap_events VALUES(?,?,?,?)",(self.namespace,event_id,candidate_id,json.dumps(payload,ensure_ascii=False,allow_nan=False)))

    def gap_event_history(self,candidate_id):
        values=[json.loads(row[0]) for row in self.execute("SELECT payload FROM gap_events WHERE namespace=? AND candidate_id=?",(self.namespace,candidate_id))]
        return sorted(values,key=lambda item:item.get("at",""))

    def save_gap_comparison(self,comparison):
        self.execute("INSERT INTO gap_comparisons VALUES(?,?,?)",
                     (comparison["comparison_id"],self.namespace,json.dumps(comparison,ensure_ascii=False,allow_nan=False)))

    def gap_comparison(self,comparison_id):
        row=self.execute("SELECT payload FROM gap_comparisons WHERE namespace=? AND comparison_id=?",
                         (self.namespace,comparison_id)).fetchone()
        return json.loads(row[0]) if row else None

    def execute(self, query, values=()):
        return self.db.execute(query.replace("?", "%s") if self.postgres else query, values)

    def transaction(self):
        return self.db.transaction() if self.postgres else self.db

    def facts(self, customer):
        return [json.loads(row[0]) for row in self.execute("SELECT payload FROM facts WHERE namespace=? AND customer=?", (self.namespace, customer))]

    def fact(self, customer, slot):
        row = self.execute("SELECT payload FROM facts WHERE namespace=? AND customer=? AND slot=?", (self.namespace, customer, slot)).fetchone()
        return json.loads(row[0]) if row else None

    def write_fact(self, customer, slot, fact, evidence_span=None):
        values = (self.namespace, customer, slot, json.dumps(fact, ensure_ascii=False, allow_nan=False))
        self.execute("INSERT INTO facts VALUES(?,?,?,?) ON CONFLICT(namespace,customer,slot) DO UPDATE SET payload=excluded.payload", values)
        event={**fact,"evidence_span":evidence_span} if evidence_span is not None else fact
        self.execute("INSERT INTO fact_events VALUES(?,?,?,?)", (self.namespace,customer,slot,json.dumps(event,ensure_ascii=False,allow_nan=False)))

    def sessions(self, customer):
        result = [json.loads(row[0]) for row in self.execute("SELECT payload FROM sessions WHERE namespace=? AND customer=?", (self.namespace, customer))]
        return sorted(result, key=lambda s: int(s["session_id"].split("_")[1]))

    def history(self):
        return [(row[0], row[1], json.loads(row[2])) for row in self.execute("SELECT call,status,payload FROM calls WHERE namespace=?", (self.namespace,))]

    def web_call(self, call_id, owner):
        row=self.execute("SELECT call_id,namespace,owner,customer,call,conversation_id,status,payload FROM web_calls WHERE call_id=? AND owner=?",
                         (call_id,str(owner))).fetchone()
        return dict(zip(("call_id","namespace","owner","customer","call","conversation_id","status","payload"),
                        (*row[:7],json.loads(row[7])))) if row else None

    def conversation_call(self, owner, conversation_id):
        row=self.execute("SELECT call_id FROM web_calls WHERE owner=? AND conversation_id=? AND status IN ('OPEN','RECONCILIATION_REQUIRED')",
                         (str(owner),conversation_id)).fetchone()
        return self.web_call(row[0],owner) if row else None

    def web_calls_for_owner(self, owner):
        rows=self.execute("SELECT call_id FROM web_calls WHERE owner=? ORDER BY call_id",(str(owner),)).fetchall()
        return [self.web_call(row[0],owner) for row in rows]

    def call_record(self, customer, call):
        row=self.execute("SELECT status,payload FROM calls WHERE namespace=? AND customer=? AND call=?",
                         (self.namespace,customer,call)).fetchone()
        return {"status":row[0],"context":json.loads(row[1])} if row else None

    def turn_history(self, customer, call):
        return [(row[0],json.loads(row[1])) for row in self.execute(
            "SELECT turn,payload FROM turns WHERE namespace=? AND customer=? AND call=? ORDER BY turn",
            (self.namespace,customer,call))]

    def web_call_result(self, call_id, result):
        with self.transaction():
            self.execute("UPDATE web_calls SET payload=? WHERE call_id=? AND namespace=? AND status='COMPLETED'",
                         (json.dumps(result,ensure_ascii=False,allow_nan=False),call_id,self.namespace))

    def mark_web_call_interrupted(self, call_id):
        with self.transaction():
            self.execute("UPDATE web_calls SET status='RECONCILIATION_REQUIRED' WHERE call_id=? AND namespace=? AND status='OPEN'",
                         (call_id,self.namespace))

    def open_call(self, customer, context):
        with self.transaction():
            if self.postgres:
                self.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", (self.namespace,))
            if any(status != "COMPLETED" for _, status, _ in self.history()):
                raise RuntimeError("Previous call requires completion/reconciliation")
            self.execute("INSERT INTO customers VALUES(?,?,?) ON CONFLICT(namespace,customer) DO NOTHING", (self.namespace, customer, "{}"))
            self.execute("INSERT INTO calls VALUES(?,?,?,?,?)", (self.namespace, customer, context["call"], "OPEN", json.dumps(context, ensure_ascii=False)))
            if context.get("api_call_id"):
                self.execute("INSERT INTO web_calls VALUES(?,?,?,?,?,?,?,?)",
                             (context["api_call_id"],self.namespace,str(context["api_owner"]),customer,context["call"],
                              context.get("conversation_id"),"OPEN","{}"))

    def fail(self, customer, call):
        with self.transaction():
            self.execute("UPDATE calls SET status='FAILED' WHERE namespace=? AND customer=? AND call=? AND status!='COMPLETED'", (self.namespace, customer, call))
            self.execute("UPDATE web_calls SET status='FAILED' WHERE namespace=? AND customer=? AND call=? AND status!='COMPLETED'",
                         (self.namespace,customer,call))

    def finalize(self, customer, call, session, *, in_transaction=False):
        if session.get("session_id") != call:
            raise ValueError("Episode call differs from lifecycle")
        from contextlib import nullcontext
        with nullcontext() if in_transaction else self.transaction():
            if self.postgres:
                self.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", (self.namespace,))
            row = self.execute("SELECT status FROM calls WHERE namespace=? AND customer=? AND call=?", (self.namespace, customer, call)).fetchone()
            if row is None or row[0] not in ("OPEN", "FINALIZING", "COMPLETED"):
                raise RuntimeError("Cannot finalize missing or failed call")
            if row[0] == "COMPLETED":
                existing = next((s for s in self.sessions(customer) if s["session_id"] == call), None)
                if existing != session:
                    raise ValueError("Completed episode cannot be rewritten")
                return
            self.execute("UPDATE calls SET status='FINALIZING' WHERE namespace=? AND customer=? AND call=? AND status='OPEN'", (self.namespace, customer, call))
        # A durable RUNNING job blocks the next call when the caller owns the transaction.
        with nullcontext() if in_transaction else self.transaction():
            if self.postgres:
                self.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", (self.namespace,))
            self.execute("INSERT INTO sessions VALUES(?,?,?,?) ON CONFLICT(namespace,customer,call) DO NOTHING", (self.namespace, customer, call, json.dumps(session, ensure_ascii=False)))
            self.execute("UPDATE calls SET status='COMPLETED' WHERE namespace=? AND customer=? AND call=? AND status='FINALIZING'", (self.namespace, customer, call))
            self.execute("UPDATE web_calls SET status='COMPLETED' WHERE namespace=? AND customer=? AND call=? AND status IN ('OPEN','RECONCILIATION_REQUIRED')",
                         (self.namespace,customer,call))
            self.execute("UPDATE jobs SET status='COMPLETED' WHERE namespace=? AND customer=? AND call=? AND kind='persist' AND status='RUNNING'",
                         (self.namespace,customer,call))

    def close(self):
        self.db.close()
