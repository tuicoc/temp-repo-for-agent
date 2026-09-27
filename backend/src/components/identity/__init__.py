"""Identity: who is speaking, and how sure we are. ``docs/design.md`` section 4.2, figure B.

Runs in ``load_context`` at the start of a call, and again on any turn that
brings a key the call has not seen or answers the confirming question.
Keys from the connection and from the words are looked up in the
organisers' CRM (``crm.get_customer``) and in the ledger's ``identities``;
the result is one of four tiers (:mod:`.resolver`). PROBABLE and AMBIGUOUS
cost exactly one question, asked so that it reveals nothing about anyone
else; the answer lifts the call to VERIFIED or leaves a new customer.
"""
