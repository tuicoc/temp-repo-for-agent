"""PolicyAgent: the soft guardrail, on Jev. ``docs/design.md`` sections 4.5 and 12.

Runs after the hard check passes and catches what a regular expression
cannot: a promise outside policy, a rule no longer in force, a remark on a
competitor's price, pressure the stock does not justify.

It reads :class:`PolicyInput` and nothing else: **no brief and no
messages**, on purpose (section 12). The advisor has the old brief, the
customer's pleading and the new price all in view, which is what makes it
soften; this agent sees only the draft, the tool results and the policy, so
an old price standing next to a new one is plain.

The model is Jev (``evaluators.policy`` in ``config/models.yaml``): one
request, one Boolean per question, each answered independently with a
probability. A draft is blocked when any probability passes its threshold;
the lab of 2026-09-23 found 0.9 right for policy questions (architecture
notes 8.5), to be set again on the team's own labelled set.

When Jev gives no answer in time (no key, throttled, timed out) the draft
passes on the hard check alone and the verdict says so: a late answer costs
the customer more than a skipped soft check, and the hard check has already
held the numbers to the tools.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from ..llm.jev import Boolean, JevUnavailable
from .base import BaseAgent

logger = logging.getLogger(__name__)

QUESTIONS = {
    "over_promise": Boolean(
        instructions=(
            "Does the reply promise something the shop policy and the tool results do not support, such as "
            "free shipping, easier returns, a delivery date, or a discount?"
        ),
    ),
    "stale_policy": Boolean(
        instructions="Does the reply state a rule, price or promotion that the tool results or the policy show has ended or changed?",
    ),
    "competitor": Boolean(
        instructions="Does the reply comment on, disparage or match another shop's price or product?",
    ),
    "false_pressure": Boolean(
        instructions=(
            "Does the reply pressure the customer with scarcity or urgency (only a few left, price rising "
            "soon) that the tool results do not confirm?"
        ),
    ),
}

#: Per question, from the lab's leave-one-out choice.
THRESHOLDS = {"over_promise": 0.9, "stale_policy": 0.9, "competitor": 0.9, "false_pressure": 0.9}

REASONS = {
    "over_promise": "Hứa điều chính sách và kết quả tool không xác nhận.",
    "stale_policy": "Nói theo giá, khuyến mãi hoặc chính sách đã hết hiệu lực.",
    "competitor": "Bình luận giá hoặc sản phẩm của cửa hàng khác.",
    "false_pressure": "Tạo áp lực khan hiếm hoặc gấp mà tool không xác nhận.",
}


@dataclass(frozen=True)
class PolicyInput:
    """What the Policy may read (section 3.2)."""

    text: str
    tool_results: tuple[dict[str, Any], ...]
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    #: Policy passages the advisor read this turn.
    policy_snippets: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyVerdict:
    passed: bool
    reasons: tuple[str, ...] = ()
    #: "jev", or "skipped:<code>" when Jev gave no answer.
    decided_by: str = "jev"
    probabilities: dict[str, float] = field(default_factory=dict)
    seconds: float = 0.0


class PolicyAgent(BaseAgent):
    """Reviews a draft against the shop's policy."""

    def __init__(self) -> None:
        super().__init__("policy")

    async def review(self, view: PolicyInput) -> PolicyVerdict:
        state = {
            "reply": view.text,
            "identity_tier": view.tier,
            "tool_results": [
                {"tool": r.get("name"), "result": (r.get("result") or {}).get("data")} for r in view.tool_results
            ],
            "policy": list(view.policy_snippets) or ["(no policy passage was read this turn)"],
        }
        try:
            decision = await self.evaluate(json.loads(json.dumps(state, ensure_ascii=False, default=str)), QUESTIONS)
        except JevUnavailable as unavailable:
            logger.info("Policy check skipped: %s", unavailable.code)
            return PolicyVerdict(True, decided_by=f"skipped:{unavailable.code}")
        probabilities = {name: float(answer.probability or 0.0) for name, answer in decision.answers.items()}
        failed = [name for name, p in probabilities.items() if p >= THRESHOLDS[name]]
        return PolicyVerdict(
            passed=not failed,
            reasons=tuple(REASONS[name] for name in failed),
            probabilities=probabilities,
            seconds=round(decision.seconds, 3),
        )

    async def review_change(self, text: str, *, kind: str, policy_snippets: tuple[str, ...] = ()) -> PolicyVerdict:
        """Check a lesson or a playbook entry before QA sees it (section 10.3).

        A failure is a tag, not a rejection: the change still reaches QA with
        the reason, because this agent can be wrong too.
        """
        return await self.review(PolicyInput(text=text, tool_results=(), tier="VERIFIED", policy_snippets=policy_snippets))
