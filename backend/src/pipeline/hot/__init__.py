"""The hot graph: one customer turn, while the customer waits. ``docs/design.md`` section 4, figure 1.

- :mod:`.state`: ``HotState`` (checkpointed per call), ``TurnInput``,
  ``HotContext`` (the raw turn and the collaborators, never checkpointed).
- :mod:`.nodes`: the seven nodes, each a thin adapter from state to a
  component or an agent and back.
- :mod:`.graph`: the wiring, ``build_graph``.

The API (``src/api/calls.py``) and the evaluation runner drive this same
graph; a call recorded as audio, a chat and a live call all go through it.
"""
