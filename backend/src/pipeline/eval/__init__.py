"""The agent under evaluation. ``docs/design.md`` section 9, figure H.

The evaluation itself is in ``evaluation/`` (its dataset, grading contracts,
checks and the organisers' grader) and runs with one command,
``evaluation/run_eval.py evaluate`` (README, section 5). This package is what
it drives:

- :mod:`.bridge`: the agent behind the harness's adapter, one process per
  scenario and configuration, JSON lines over a pipe;
- :mod:`.runner`: the agent assembled for a run, and its database;
- :mod:`.extract_command`: the extraction call the harness makes per turn.
"""
