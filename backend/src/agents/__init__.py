"""The agents. ``docs/design.md`` section 12.

| Agent | When | Reads | Returns |
|---|---|---|---|
| ``AdvisorAgent`` | every turn | the slice of section 3.2 | a draft, tool results |
| ``PolicyAgent`` (Jev) | every turn | draft, tool results, policy | violations |
| ``MemoryAgent`` | after the call | transcript, current facts | what to write |
| ``QaAgent`` | after the call | transcript, rubric | scores, a lesson |
| ``SimulatorAgent`` | evaluation only | persona, outline | the customer's turns |

None of them holds state: the hot graph owns it, and hands each a slice.
The router is not here: ``route`` is rules in the harness (section 4.3).
"""

#: Structured-output classes that may appear in a checkpoint. None since the
#: advisor answers in plain text and holds no checkpoint of its own.
CHECKPOINTED_TYPES: tuple[type, ...] = ()
