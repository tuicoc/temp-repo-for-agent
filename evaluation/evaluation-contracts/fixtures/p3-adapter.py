"""Synthetic scripted P3 integration fixture; NEVER a real Agent benchmark."""
import copy
from datetime import datetime, timezone
import re

FIRST_TEXT = "Phòng chị bao nhiêu m²? Máy giá 5000000 đồng, giao 2 ngày."
SECOND_TEXT = "Vẫn phòng 30 m² đúng không ạ? Vẫn phòng 30 m² đúng không ạ?"


def stamp():
    return datetime.now(timezone.utc).isoformat()


class FixtureAdapter:
    capabilities = ("business_tools", "memory_isolation", "memory_read_gate", "after_call_barrier",
                    "snapshots", "briefs", "timestamps", "usage")
    retry = {"agent": 0, "tool": 0}

    def open_scenario(self, context):
        self.runtime = context
        self.store, self.history = {}, []
        self.customer_id = "FIXTURE-PROFILE-ONLY"
        self.emit = context["emit"]

    def snapshot(self, visible=False):
        facts = list(self.store.values()) if not visible or self.runtime["memory_read_previous"] else []
        return {"customer_id": self.customer_id, "namespace": self.runtime["namespace"],
                "facts": copy.deepcopy(facts), "writes": copy.deepcopy(self.writes)}

    def start_call(self, context):
        self.call, self.turn, self.writes, self.working = context, 0, [], []
        identified = stamp()
        self.runtime["call_tool"]("crm.get_customer", {"phone": context["customer_phone"]})
        visible = self.snapshot(visible=True)
        ready = stamp()
        brief = {"customer_phone": context["customer_phone"], "is_returning": True,
                 "n_previous_sessions": len(self.history), "last_session": None,
                 "profile_facts": {f["key"]: f["value"] for f in visible["facts"]},
                 "products_advised": [], "open_blockers": [], "must_not_ask": [f["key"] for f in visible["facts"]],
                 "suggested_opening": "Scripted fixture only", "generated_at": ready,
                 "latency_ms": round((datetime.fromisoformat(ready) - datetime.fromisoformat(identified)).total_seconds() * 1000)} if visible["facts"] else None
        return {"customer_id": self.customer_id, "memory_snapshot": visible, "call_brief": brief,
                "identified_at": identified, "brief_ready_at": ready}

    def run_turn(self, text):
        request = stamp()
        self.turn += 1
        self.working.append(text)
        match = re.search(r"(\d+)\s*m2", text)  # Fixture memory ingests actual customer text, not gold.
        if match:
            context = {key: self.call[key] for key in ("run_id", "config", "scenario_id", "call")}
            context["turn"] = self.turn
            origin = {"context": context, "field": "customer_text"}
            fact = {"key": "room_area_m2", "value": int(match[1]), "customer_id": self.customer_id,
                    "source": origin, "valid_from": self.call["on"] + "T00:00:00+07:00", "valid_until": None, "state": "active"}
            self.store[fact["key"]] = fact
            self.writes.append({key: fact[key] for key in ("key", "value", "customer_id", "source")})
            self.writes[-1]["op"] = "set"
        completed = stamp()
        return {"agent_text": FIRST_TEXT if self.call["call"] == "call_1" else SECOND_TEXT,
                "mode": "nonstream", "request_at": request, "first_token_at": completed, "completed_at": completed,
                "memory_snapshot": self.snapshot(), "usage": None,
                "usage_missing_reason": "Scripted fixture has no model billing measurements"}

    async def end_call(self):
        self.history.append(list(self.working))
        return {"completed": True, "barrier_complete": True, "memory_snapshot": self.snapshot()}

    def close_scenario(self):
        pass


def factory():
    return FixtureAdapter()
