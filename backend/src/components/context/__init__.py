"""Context: what reaches the prompt, what is cut, and when the thread is compacted.

``docs/design.md`` section 4.4. The brief asks outright "what goes into the
prompt and what is cut", so the answer is a declared order, not something
buried in a prompt.

- :mod:`.budget`: the sections in priority order within a token allowance,
  cut from the bottom; warnings are never cut.
- :mod:`.compact`: old turns folded into ``working_summary`` once the call
  grows long, the last four turns kept whole.
"""
