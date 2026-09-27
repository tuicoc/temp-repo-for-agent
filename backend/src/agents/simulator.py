"""SimulatorAgent: the customer, in evaluation only. ``docs/design.md`` section 9.8.

Follows the organisers' specification (``simulator/customer_simulator_spec.md``):
a standard persona from ``personas.json``, eight reaction rules, patience by
persona and by call, temperature 0.3 with a fixed seed over three seeds, at
most twelve customer turns, a mandatory log. It never sees the scenario's
grading fields. Without patience a simulator would cheerfully answer a fifth
time and the system would look better than it is.

Never part of the product. Status: not built; the scored runs use the
scenarios' written ``customer_turns``.
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent


class SimulatorAgent(BaseAgent):
    """A customer who follows a script and runs out of patience."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        super().__init__("simulator")
        self.scenario = scenario
        self.patience = 3

    async def reply(self, agent_said: str) -> str | None:
        """The customer's next line, or None when they hang up."""
        raise NotImplementedError("SimulatorAgent.reply: docs/design.md section 9.8")
