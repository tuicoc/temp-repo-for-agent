"""Memory: what the shop knows about each customer. ``docs/design.md`` section 5, figure C.

Read side, in ``load_context`` during a call:

- :mod:`.recall`: ``retrieve`` (the memory switch) and ``refresh`` (asking
  the tools, for the day of the call, whether what the brief cites still
  holds);
- :mod:`.brief`: the Call Brief, a pure function of the ledger.

Write side, in ``after_call`` once the call has ended, driven by the
MemoryAgent, the only writer of the ledger:

- :mod:`.ontology`: the organisers' flat slot names, their kinds and lifetimes;
- :mod:`.gate`: the deterministic doors, and who wins a conflict;
- :mod:`.ledger`: the operation for each candidate, append-only.
"""
