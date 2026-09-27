"""What is live, rounds, and going back. ``docs/design.md`` section 10.4, figure I.

A version pointer per artifact: the FAQ block and the playbook. Rolling back is
moving the pointer (``faq_active`` to the previous version) or marking one
playbook entry ``revoked``; nothing is deleted.

**Rounds for the report.** A round is one full run of the golden set, taken
once a batch of changes is in, and each round changes one thing:

| Round | Configuration |
|---|---|
| R0 | before any change; baseline and system |
| R1 | FAQ patched through the Gap Loop |
| R2 | first batch of playbook entries |
| R3 | second batch, or the revocation of a harmful entry |

All on the frozen golden set, same manifest except the version fields. Since
each round changes one thing, the gap between two neighbouring rounds is the
effect of one mechanism, which is the analysis of harmful improvements the
brief asks for; no separate ablation job.

Status: not built.
"""

from __future__ import annotations

from typing import Literal

Artifact = Literal["faq", "playbook"]


async def active(artifact: Artifact) -> str:
    """The live version of *artifact*."""
    raise NotImplementedError("improvement.versions: docs/design.md section 10.4")


async def publish(artifact: Artifact, *, reason: str) -> str:
    """Make a new version of *artifact* the live one; its name."""
    raise NotImplementedError("improvement.versions: docs/design.md section 10.4")


async def rollback(artifact: Artifact, to_version: str) -> None:
    """Point *artifact* back at *to_version*."""
    raise NotImplementedError("improvement.versions: docs/design.md section 10.4")


async def revoke_entry(entry_id: str, *, reason: str) -> None:
    """Mark one playbook entry revoked; the rest of the playbook stays."""
    raise NotImplementedError("improvement.versions: docs/design.md section 10.4")
