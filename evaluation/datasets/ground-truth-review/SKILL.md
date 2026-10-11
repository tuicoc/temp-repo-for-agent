---
name: ground-truth-review
description: Review, approve, or revise evaluation scenarios and ground-truth labels in this project's evaluation data. Use before adding a test case to model-backed evaluation, or changing success conditions, expected outcomes, facts, or grading labels; not for ordinary evaluator code fixes.
---

# Ground-truth review for evaluation data

This is the single instruction file for creating, importing, reviewing, and revising team evaluation data. Put new team data under `evaluation/datasets/`; treat BTC sources under `evaluation-contracts/sources/btc/` as immutable references. A BTC schema defines the shape, not the truth of an answer. Verify prices, promotions, inventory, order state, and effective dates against the pinned BTC catalog, policy, and mock tools. The seven BTC public samples are development examples; they are not the future organiser golden set. Do not use frozen or hidden cases to teach FAQ, Reflection, or Exemplar Bank.

Before running a new case, check the BTC scenario format and the team's `Scenario` contract, then run the offline preflight. Every call needs an independently reviewed grading method, tool expectations for both full and baseline, source/provenance and PII decision. Reject unsupported adapter inputs such as `seed_history` rather than silently dropping them. A structurally valid JSON file with a wrong business fact or unsupported field is not ready. Keep new or corrected labels in a new revision; never overwrite a used revision or historical run.

The five `output (1)` scenarios already contain ground truth. `datasets/output1-btc-diagnostic-v1/` is a derived, BTC-compatible diagnostic revision, not approved official GT. Its `conversion-report.json` records every changed field; `official_gt_approved: false` must remain truthful. `QaAgent` and model judgments can propose or flag labels, but cannot approve their own labels. A human reviewer makes the final decision.

## Before changing data

1. Read the source scenario in `output (1)/scenarios/`, its conversation and judgment if relevant, the derived scenario, `conversion-report.json`, and `output (1)/review/needs_manual_review.csv` for flagged cases. Check claims against the pinned BTC policy/catalog/mock data rather than model output alone.
2. For each changed `success_if`, `expected_outcome`, `must_carry_over`, `must_not_ask`, `ground_truth_facts`, or grading method/criterion, record source value, proposed value, evidence, reviewer, and decision: keep, revert, or revise. Distinguish a business outcome from a proxy tool call. Do not make a criterion easier solely to improve the score.
3. If evidence is missing or the reviewer has not decided, leave the label disputed/pending and the dataset diagnostic. Never turn missing GT, usage, or trace into zero or PASS.

## Publish a revision

- Preserve `output (1)/`, organiser/BTC sources, existing dataset revisions, and historical run folders. Do not overwrite a revision already used by a run.
- Change the transformation in `normalize_output1.py` and write a new versioned destination (for example `output1-btc-diagnostic-v2`), with an updated conversion report and source hashes. Update the product dataset pointer in `product.py` only after the new revision passes schema/provenance checks and the human decisions are recorded.
- Keep reviewer evidence with the new revision. Mark approval only for the scope actually reviewed; one approved field or call does not approve the whole dataset. If the existing conversion schema cannot express that distinction, document it explicitly rather than setting `official_gt_approved: true` broadly.
- Run the deterministic contract/provenance checks and a small regression check for any new transformation logic. Run model-backed evaluation only when requested or authorized; compare the same pinned cohort and report label changes separately from agent changes.

The result should tell the user which calls/fields were approved, which remain pending, why, and which dataset revision a future run should use.

## Gate trước khi chạy model với test case mới

Áp dụng cho **mỗi scenario/call mới**, kể cả khi đã có `success_if` trong JSON. Hoàn thành các việc sau trước khi gọi `run_eval.py evaluate`:

1. Ghi **phương pháp chấm TSR trước khi chạy** cho từng scenario/call trong grading contract: `assertion_only` nếu toàn bộ điều kiện quyết định thành công kiểm được bằng code; `judge`/hybrid chỉ khi chất lượng lời thoại là điều kiện bắt buộc và khó assert. Tách rõ điều kiện quyết định TSR với judge chỉ dùng làm chẩn đoán. Với mỗi điều kiện, ghi expected PASS/FAIL, bằng chứng cần có, cách xử lý thiếu bằng chứng (`INCOMPLETE`), nguồn, người duyệt và trạng thái. Một scenario chỉ đạt khi mọi call/điều kiện bắt buộc đạt; không suy ra PASS từ nhãn tạo dữ liệu.
2. Nếu chọn assertion, viết điều kiện có thể kiểm chứng (tên tool + đối số + kết quả/trạng thái khi cần, tool bị cấm, hoặc văn bản có thể kiểm chắc bằng code). Nêu giới hạn của phép dò từ khóa `must_say_any`; không gọi đó là đánh giá ngữ nghĩa. Nếu chọn judge, gắn ID tiêu chí J01–J12 và điều kiện áp dụng từ rubric BTC, xác định verdict PASS/FAIL nào quyết định TSR, transcript/GT nào được đưa vào prompt và cách kiểm câu trích dẫn. Không dùng `overall_pass` trong `output (1)/judgments/` làm nhãn người: đó là judge của hội thoại mẫu, không phải verdict của run agent. Chưa có judge chạy thật hoặc verdict thiếu hợp lệ thì để hybrid TSR `INCOMPLETE`; không ghi đè TSR assertion/BTC. Muốn báo độ đồng thuận cần ≥20 cặp `(call, criterion)` do người chấm độc lập theo giao thức BTC.
3. Xác định kỳ vọng tool từ nguồn và chính sách: tool bắt buộc, tên và đối số; tool bị cấm; tool chỉ bắt buộc khi một điều kiện xảy ra; read-only tool phụ trợ được phép hay không. Không tự biến tool có điều kiện thành yêu cầu vô điều kiện, hoặc coi thiếu positive label là “cấm mọi tool”. Ghi nguồn, bằng chứng, người duyệt và trạng thái cho từng quyết định; chưa duyệt độc lập thì giữ nhãn diagnostic.
4. Với set mới, ghi nhãn mọi scenario/call vào file `tool_labels` và phiếu duyệt từng call vào `gt_review` trong `evaluation/datasets/`; trỏ cả hai từ `registry.json`. Positive label phải khớp `success_if.tool_called` và `args_match`. `product.prepare()` nối nhãn `ExpectedToolCalls` vào grading contract cho **cả** `full` và `baseline_no_memory` trên cùng cohort, model–prompt–tools–KB; chỉ memory khác. `evaluation/tool_expectations.py` chỉ giữ nhãn 5 case legacy, không thêm case mới vào đó. Giữ các kiểm tra `must_not_call_tools`/business error riêng. Nếu cơ chế chấm hiện tại chưa thực thi phương pháp đã gán (nhất là hybrid judge), dừng và nối evaluator trước; không chỉ ghi `mode: judge` rồi chạy `evaluate` như thể đã được chấm.
5. Chạy `run_eval.py data-check --set <id>` rồi test deterministic và `product.prepare()` trong thư mục tạm để kiểm schema, provenance, hai cấu hình và `execution_gate.allowed`. `prepare()` không gọi model. Bất kỳ lỗi schema/GT/nhãn nào phải sửa trong revision đầu vào trước khi chạy; với golden BTC tương lai, giữ nguyên bản gốc để đối chiếu và mở rộng adapter nếu schema mới có field chưa hỗ trợ, không âm thầm bỏ field. Chỉ chạy model khi tất cả kiểm tra này đạt, không có case/call thiếu nhãn hoặc dispute chưa được phản ánh đúng trong báo cáo. Nếu chưa đạt, báo rõ blocker thay vì dùng `evaluate` để thử.

Xem `evaluation/docs/TOOL-CALL-LABELS.md` để hiểu quyết định hiện tại của 5 scenario. Run cũ và nguồn BTC vẫn bất biến. Gate này đảm bảo **đủ nhãn và chạy được**, không tự biến nhãn diagnostic thành ground truth chính thức.
