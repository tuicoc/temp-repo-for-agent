"""The hot graph's wiring. ``docs/design.md`` section 4.

Seven nodes, one to one with the brief's figure C.2:

| Node | Box in the brief's figure |
|---|---|
| ``perceive`` | PERCEIVE |
| ``load_context`` | RESOLVE IDENTITY, RETRIEVE |
| ``route`` | how to PLAN this turn |
| ``advisor`` | PLAN, GUARDRAIL before a write tool, ACT, OBSERVE |
| ``guard`` | GUARDRAIL on the reply |
| ``respond`` | ACT (the reply) |
| ``persist`` | PERSIST |

Edges: ``START -> perceive -> load_context -> route -> advisor -> guard``;
``guard`` blocked with regenerations left goes back to ``advisor``, else on
to ``respond -> persist -> END``. ``load_context`` works on the first turn of
a call and on a turn that brings a new key or answers the confirming
question; on every other turn it passes straight through.

Hanging up is not in the graph: the API starts ``after_call`` as a task,
because nobody waits for it (section 2).
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from .nodes import advisor, after_guard, guard, load_context, perceive, persist, respond, route
from .state import HotContext, HotState, TurnInput

#: Every node, in order.
NODES: tuple[str, ...] = ("perceive", "load_context", "route", "advisor", "guard", "respond", "persist")


def build_graph(*, checkpointer: BaseCheckpointSaver | None = None) -> Any:
    """Compile the hot graph. Compile once per process and share it: the
    graph holds no per-call state, the checkpointer does."""
    graph = StateGraph(HotState, context_schema=HotContext, input_schema=TurnInput)
    graph.add_node("perceive", perceive)
    graph.add_node("load_context", load_context)
    graph.add_node("route", route)
    graph.add_node("advisor", advisor)
    graph.add_node("guard", guard)
    graph.add_node("respond", respond)
    graph.add_node("persist", persist)

    graph.add_edge(START, "perceive")
    graph.add_edge("perceive", "load_context")
    graph.add_edge("load_context", "route")
    graph.add_edge("route", "advisor")
    graph.add_edge("advisor", "guard")
    graph.add_conditional_edges("guard", after_guard, ["advisor", "respond"])
    graph.add_edge("respond", "persist")
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=checkpointer, name="hot")
