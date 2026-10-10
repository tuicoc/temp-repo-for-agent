"""Fixture-only echo adapter. Never a business Agent or quality benchmark."""
import copy
from datetime import datetime, timezone
import time


class FixtureAdapter:
    capabilities = ("business_tools", "memory_isolation", "memory_read_gate", "after_call_barrier",
                    "snapshots", "briefs", "timestamps", "usage")
    retry = {"agent": 0, "tool": 0}

    def open_scenario(self, context):
        self.context = context
        self.history = copy.deepcopy(context["seed_history"])
        self.emit = context["emit"]
        self.emit({"role": "runtime", "kind": "seeded_once", "seed_count": len(self.history)})

    def start_call(self, context):
        clock = time.monotonic()
        identified = datetime.now(timezone.utc).isoformat()
        self.call = context
        self.working = []
        self.previous = copy.deepcopy(self.history) if context["memory_read_previous"] else []
        crm = self.context["call_tool"]("crm.get_customer", {"phone": context["customer_phone"]})
        self.emit({"role": "runtime", "kind": "crm_visible", "result": crm})
        self.emit({"role": "runtime", "kind": "memory_read_gate", "visible_history": self.previous})
        ready = datetime.now(timezone.utc).isoformat()
        brief = {"customer_phone": context["customer_phone"], "is_returning": True,
                 "n_previous_sessions": len(self.previous), "last_session": None,
                 "products_advised": [], "open_blockers": [], "must_not_ask": [],
                 "suggested_opening": "FIXTURE ECHO", "generated_at": ready,
                 "latency_ms": round((time.monotonic() - clock) * 1000)} if self.previous else None
        return {"memory_snapshot": {"namespace": self.context["namespace"], "history": self.previous},
                "call_brief": brief, "identified_at": identified, "brief_ready_at": ready}

    def run_turn(self, customer_text):
        started = datetime.now(timezone.utc).isoformat()
        clock = time.monotonic()
        self.working.append(customer_text)
        text = "FIXTURE ECHO: " + customer_text
        completed = datetime.now(timezone.utc).isoformat()
        self.emit({"role": "runtime", "kind": "working_context", "texts": list(self.working)})
        return {"agent_text": text, "mode": "nonstream", "request_at": started,
                "completed_at": completed, "first_token_at": completed,
                "elapsed_ms": (time.monotonic() - clock) * 1000,
                "usage": None, "usage_missing_reason": "Fixture has no provider/charge measurement"}

    async def end_call(self):
        self.history.append({"call": self.call["call"], "on": self.call["on"], "texts": list(self.working)})
        self.emit({"role": "runtime", "kind": "after_call_committed", "call": self.call["call"]})
        return {"completed": True, "barrier_complete": True, "outcome": "fixture_only",
                "memory_snapshot": {"namespace": self.context["namespace"], "history": copy.deepcopy(self.history)}}

    def close_scenario(self):
        self.emit({"role": "runtime", "kind": "closed"})


def factory():
    return FixtureAdapter()
