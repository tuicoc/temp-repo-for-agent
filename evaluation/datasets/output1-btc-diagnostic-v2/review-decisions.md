# Human review — diagnostic v2 (2026-10-10)

Reviewer: project owner (approval in the evaluation discussion). Scope: only the decisions below. `official_gt_approved` remains `false`; the other converted fields in `conversion-report.json` are still pending review.

| Scenario/call | Field | v1 | v2 decision and reason |
| --- | --- | --- | --- |
| SCN-GEN-0002/call_2 | `must_carry_over` | `tracking` | **Keep.** Reviewer confirmed the tracking code is mandatory for this case. No label change. |
| SCN-GEN-0003/call_2–3 | `success_if.must_say_any` | `mã đơn`, `thông tin đơn` | **Revise.** Also accept `chưa ghi nhận đơn` or `chưa có đơn`: the approved behavior is to say no order exists, not to recite a particular phrase. `must_not_call_tools: [order.create]` stays. |
| SCN-GEN-0004/call_1–3 and SCN-GEN-0005/call_1–2 | `success_if.must_say_any` | `xác nhận`, `cho em biết tên` | **Revise.** Also accept `cho em xin tên` as an equivalent identity-confirmation request. The prohibition on order tools before confirmation stays. |

SCN-GEN-0005/call_1 remains a real failure in run `20261010-173702`: the agent did not ask for the caller's name. This revision does not add a phrase that would make that response pass. Product-side options are recorded in a local teacher handoff outside this repo; product code is unchanged.

The v1 source, `output (1)`, and historical run evidence remain immutable. Compare new results against v1 with the label change called out explicitly; a higher TSR caused by revised wording is not an agent improvement.
