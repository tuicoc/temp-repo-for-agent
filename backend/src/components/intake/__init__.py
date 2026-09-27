"""Intake: what the customer said, made into text the system can trust.

``docs/design.md`` section 4.1 and figure A. Three sources — a chat message,
a live call through local ASR, a recording — each with its own cleanup, then
one normaliser for all of them, because two normalisers drift apart within
weeks and number normalisation is exactly where Entity Accuracy is scored.

On a turn, in order, under 50 ms and with no model:

1. :func:`.text.clean`: teencode and abbreviations ("sp nay co ship cod k a");
2. :func:`.text.nfc`;
3. :func:`.itn.normalise`: money, phone numbers, dates and times, dates
   against the virtual clock;
4. :func:`.pii.tokenise`: personal data into the call's vault as tokens.

The input mode is recorded for the trace: ``clean``, ``asr_transcript`` or
``chat_teencode``.
"""
