"""Orchestration: which lane a turn takes. ``docs/design.md`` section 4.3.

The role the brief's table C.3 calls "Orchestrator / Router" is the ``route``
node of the harness, written as rules: it reads only what is already in the
state, calls no model and no tool, and gives the same answer every time.
A lane is one configuration of the AdvisorAgent: an instruction plus a set
of tools (``config/lanes.yaml``).

A routing model is added after the rules only if they are measured to
misroute real cases (Appendix E).
"""
