"""After the call, nobody waiting. ``docs/design.md`` sections 2, 4.7 and 5.4.

Hanging up starts :func:`.after_call.after_call` as a task in the API's own
process: no queue and no separate worker (section 2). Two branches over the
same tokenised transcript and tool log:

| Branch | Agent | Writes |
|---|---|---|
| remember this customer | ``MemoryAgent``: extract, gate, commit, summarize | the ledger, through ``memory_writer`` |
| score and learn | ``QaAgent``: score, tag, reflect | the call's tags; lessons once built |

If it fails, the call stays marked as not remembered and is run again when
the API starts. The evaluation runner calls the same function, synchronously,
between two calls of a scenario.
"""
