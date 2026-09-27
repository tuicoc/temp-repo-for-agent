"""Which utterances count as a turn. ``docs/design.md`` section 4.11.

Voice activity alone cannot tell a caller cutting in from a caller saying
"ừ" to show they are listening, from a cough, or from the line hissing. The
production voice stacks settle it on the words once they are recognised:
LiveKit's agents take an interruption only past ``min_interruption_words``
and resume speaking after a ``false_interruption_timeout`` with no words
(https://docs.livekit.io/agents/logic/turns/); Pipecat's
``MinWordsInterruptionStrategy`` does the same. This is that rule, pure so it
can be tested without a microphone:

- a hesitation ("ừm", "ờ", "à") is never a turn;
- while the assistant is talking or still working out its answer, an
  utterance must have at least ``min_words`` words and not be backchannel
  alone ("dạ", "vâng", "ok") to interrupt it;
- while the assistant is listening, anything with a word in it is a turn,
  because "vâng" is a real answer to "chị lên đơn luôn nhé?".

Pure: no audio packages, so the voice session and its tests import it freely.
"""

from __future__ import annotations

import re

HESITATION = frozenset({"ừ", "ừm", "ừa", "ờ", "ơ", "à", "á", "ư", "hử", "hả", "ồ", "ô", "hmm", "hm", "uh", "um", "ờm"})
BACKCHANNEL = HESITATION | frozenset({"dạ", "vâng", "ok", "okay", "oke", "đúng", "rồi", "ạ", "thế", "vậy", "à ừ"})


def counts_as_turn(text: str, *, busy: bool, min_words: int) -> tuple[bool, str]:
    """Whether *text* takes a turn, and if not, why."""
    words = re.findall(r"\w+", text.lower())
    if not words:
        return False, "nothing recognised"
    if all(word in HESITATION for word in words):
        return False, "a hesitation"
    if busy:
        if len(words) < min_words:
            return False, f"under {min_words} words while the assistant was busy"
        if all(word in BACKCHANNEL for word in words):
            return False, "listening sounds while the assistant was busy"
    return True, ""
