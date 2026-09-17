"""The base every agent inherits from.

The reference project defines its own ``Tool`` wrapper, its own ``ToolResult``,
and its own ReAct loop. That code predates the framework growing its own, and
copying it here would repeat the mistake this project already avoided in the
LLM factory: hand-writing what LangChain already does.

So this base is thin on purpose. It owns three things and delegates the rest:

- **Which model an agent runs on.** Read from ``agents:`` in
  ``config/models.yaml``, built through ``LLMFactory`` so the shared rate
  limiter, the token ledger and Langfuse come along.
- **Compiling the agent once.** ``langchain.agents.create_agent`` returns a
  compiled LangGraph implementing the ReAct loop with a ``ToolNode``, which is
  what ``docs/flow.md`` section 10 specifies. Passing ``response_format``
  constrains the final answer to a schema, so the reply is a validated object
  rather than text to parse.
- **A place to put the contract.** Subclasses declare ``SYSTEM_PROMPT``,
  ``RESPONSE_FORMAT`` and ``tools()``, and implement ``process``.

Tools are plain functions decorated with ``@tool`` from ``langchain_core``.
The decorator derives the argument schema from the type hints and the
docstring, so the description the model reads and the validation the code gets
come from one place. Parameter descriptions belong under an ``Args:`` heading:
without it the generated schema is silently incomplete and models start
guessing arguments.

Nothing here is a "module" in the reference's sense — no profile, memory,
knowledge or think layer. Those are this project's own, and they arrive with
the sections of ``docs/flow.md`` that define them. Fixing their interfaces
before anything is built against them would be guessing.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Sequence

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from ..config.config_manager import get_models_config
from ..llm.factory import LLMFactory

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for every agent in the system.

    A subclass supplies its prompt, its tools and its output shape, then
    implements :meth:`process`. It gets a compiled ReAct graph for free.
    """

    #: Instructions sent with every call.
    SYSTEM_PROMPT: str = ""

    #: Pydantic model the final answer is constrained to. None means free text.
    RESPONSE_FORMAT: type[BaseModel] | None = None

    def __init__(
        self,
        name: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """Build the agent.

        ``provider`` and ``model`` override what ``config/models.yaml`` routes
        this agent to. The chat page offers a model picker, so the override is
        a first-class argument rather than something callers patch in.
        """
        self.name = name

        config = get_models_config().agent_llm_config(name)
        if provider and model:
            config = get_models_config().llm_config(provider, model)
        elif model:
            config = {**config, "model": model}
        self.model_name = config["model"]
        self.llm = LLMFactory.create_llm(config, agent_name=name)

        self._tools = list(self.tools())
        self._graph = create_agent(
            model=self.llm,
            tools=self._tools,
            system_prompt=self.SYSTEM_PROMPT or None,
            response_format=self.RESPONSE_FORMAT,
        )
        logger.info(
            "Agent '%s' ready on %s | tools: %s",
            name,
            self.model_name,
            [t.name for t in self._tools] or "none",
        )

    # ── running ───────────────────────────────────────────────────────────

    def invoke(self, messages: list[Any], **kwargs: Any) -> dict[str, Any]:
        """Run the ReAct loop over *messages* and return the graph's output.

        With ``RESPONSE_FORMAT`` set, the result carries the validated object
        under ``structured_response``.
        """
        return self._graph.invoke({"messages": messages}, **kwargs)

    def stream(self, messages: list[Any], **kwargs: Any):
        """Yield message chunks as the model produces them.

        ``stream_mode="messages"`` gives token-level chunks, which is what an
        SSE endpoint needs.
        """
        yield from self._graph.stream(
            {"messages": messages}, stream_mode="messages", **kwargs
        )

    # ── what subclasses provide ───────────────────────────────────────────

    def tools(self) -> Sequence[BaseTool]:
        """The tools this agent may call. Override; the default is none.

        An empty list is a real answer, not an oversight: ``docs/flow.md``
        section 9 gives some lanes no tools so that "the agent called no tool"
        is mechanically true rather than a promise made in a prompt.
        """
        return []

    @abstractmethod
    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Entry point. Takes the current state, returns the keys to update."""
