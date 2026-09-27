"""What every agent has in common: its models come from config, by its name.

An agent's name is its key in ``config/models.yaml``. Under ``agents`` it
names a chat model, which :class:`~src.llm.factory.LLMFactory` builds with the
shared rate limiter and the token ledger already on it. Under ``evaluators``
it names an evaluation model such as Jev, reached through
:func:`~src.llm.jev.evaluate`. Either way, changing the model an agent uses
is one line of config, the same for every agent, and nothing below an agent
picks a model by itself.

That is all the base does. The agents differ too much for more: the Advisor
is a tool loop, the Policy one request to Jev, the Memory and QA agents run
after the call. None holds state between calls (``docs/design.md``,
principle 2). Each builds the rest from ``src/components`` and the framework.
"""

from __future__ import annotations

from typing import Any, Mapping

from langchain_core.language_models import BaseChatModel

from ..config.config_manager import get_models_config
from ..llm import jev
from ..llm.factory import LLMFactory


class BaseAgent:
    """A named agent whose models are resolved from ``config/models.yaml``."""

    def __init__(
        self,
        name: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        generation: Mapping[str, Any] | None = None,
    ) -> None:
        """Resolve the agent's chat model, if it has one.

        ``provider`` and ``model`` override the routing in the file, for the
        Admin page's model picker; the agent's own ``generation`` block still
        applies over the top, so a different model changes who answers, not
        how much this agent may say.

        ``generation`` overrides individual parameters (today only
        ``temperature``) for an operator changing them at runtime. Anything
        else is refused, so the file stays the one place a model's parameters
        are defined.

        An agent with no entry under ``agents`` and no override has no chat
        model (``llm`` is None): the Policy asks Jev and nothing else.
        """
        self.name = name
        self.llm: BaseChatModel | None = None
        self.model_name: str | None = None

        models = get_models_config()
        if not (provider or model or name in models.agents):
            return

        if provider and model:
            config = models.llm_config(provider, model, agent=name)
        else:
            config = models.agent_llm_config(name)
            if model:
                config = {**config, "model": model}
        if generation:
            unknown = set(generation) - {"temperature"}
            if unknown:
                raise ValueError(f"Cannot override {sorted(unknown)} at runtime; edit config/models.yaml")
            config = {**config, **generation}
        self.model_name = config["model"]
        self.llm = LLMFactory.create_llm(config, agent_name=name)

    async def evaluate(
        self, state: jev.State, questions: Mapping[str, jev.Question]
    ) -> jev.Decision:
        """Ask the evaluation model routed to this agent under ``evaluators``.

        Raises :class:`~src.llm.jev.JevUnavailable` rather than waiting; the
        agent decides what to do without an answer.
        """
        return await jev.evaluate(self.name, state, questions)
