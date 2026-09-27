"""Handoff and copilot: a person takes the call. ``docs/design.md`` section 4.10, figure G.

A handoff is not an ending; it switches the call's mode. The advisor calls
``handoff.transfer`` with a brief in the organisers' schema; the harness
records it, says the bridging line once, and turns the call to copilot.
A consultant accepts on the Agent Console and talks on in the same session;
every sentence they send passes the same guard as the advisor's.

- :mod:`.render`: the Handoff Brief as a consultant reads it, in ten seconds.
- :mod:`.copilot`: what the consultant's choice on a suggestion records.
"""
