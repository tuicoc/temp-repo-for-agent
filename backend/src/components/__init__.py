"""What the system can do, one package per function.

Each package holds the logic of one function of ``docs/design.md`` and knows
nothing about the order things run in; that is ``src/pipeline``'s job. A
component takes typed input and returns typed output, so the same check
serves the advisor's draft, the consultant's text in copilot mode, and the
evaluator's transcripts, none of which has to be a graph.

| Package | Section | What it does |
|---|---|---|
| ``intake`` | 4.1 | Clean, normalise and tokenise what the customer said |
| ``identity`` | 4.2 | Find who is speaking, and how sure we are |
| ``memory`` | 4.2, 5 | The Call Brief and whether it still holds; after the call, what to write and who wins |
| ``orchestration`` | 4.3 | Which lane a turn takes, by rules |
| ``context`` | 4.4 | What goes into the prompt, what is cut, when to compact |
| ``guardrails`` | 4.4, 4.5, 4.9 | Checks before a write tool and on a reply, and the safe lines |
| ``handoff`` | 4.6, 4.10 | Handing a call to a person, and the copilot that follows |
| ``voice`` | 4.11 | VAD, turn detection, ASR and TTS for a live call |
| ``evaluation`` | 9 | The rubric and the scorers |
| ``improvement`` | 10 | Gap Loop and Reflection |

:mod:`.clock` is the virtual clock every one of them reads the day from.

Imports go one way: ``pipeline`` uses ``agents`` and ``components``;
``agents`` use ``components``; ``components`` use ``llm``, ``mcp`` and
``config``. A component never imports ``pipeline`` or ``agents``.
"""
