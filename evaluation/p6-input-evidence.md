# P6 — nhập billing ledger và casebook review

Triển khai 07/10/2026. Đọc [README](README.md) → tài liệu này → `eval_harness/p6_evidence.py`. Hai input dưới đây là **staging sidecars**, không đổi contracts.schema.json/BTC, không sửa run đã đóng. Producer xuất thư mục mới có `artifacts.lock.json` theo helper `datasets.close_output`; importer kiểm exact inventory/hash bằng locked_run. Lock chứng minh bytes, không chứng minh người review/provider có thẩm quyền.

## Lệnh

```sh
evaluation/asr/.venv/bin/python -B evaluation/run_eval.py report --run /path/to/closed-p4 --asr-run /path/to/closed-p5 --usage-run /path/to/closed-billing --casebook-run /path/to/closed-review --out evaluation/runs/p6-reviewed-new
```

Hai flags mới optional; không có input thì giữ cách xử lý cũ: missing usage/casebook INCOMPLETE. Input có nhưng sai hash/context/coverage/format bị reject, không fallback sang số0 hoặc receipts cũ. Output copy nguyên bytes dưới `usage/` và `casebook-review/`, rebase references trong errors mới; recheck source locks trước khi đóng output. Không dùng flags để sửa source P3/P4 validation cũ.

## 1. Billing ledger

File `usage-ledger.json` có đúng3keys:

- `schema_version`: `p6-usage-ledger-v1`.
- `run_id`: đúng manifest run.
- `configs`: đúng hai keys `full`, `baseline_no_memory`.

Mỗi config có đúng `raw_records_ref` và `receipts`:

- `raw_records_ref`: AssetRef whole file đúng `full/raw-records.json` hoặc `baseline_no_memory/raw-records.json`, relative tới P4 `evidence/`, **hash bytes collector đã đóng**, không hash của ledger root.
- `receipts`: list `{raw_index, receipt_ref}`. `raw_index` là index JSON array thật trong raw-records, không số dòng JSONL; `receipt_ref` relative tới root billing input.

Expected indices được importer lấy từ raw records: mọi `kind=hook_request` và mọi `kind=adapter_message, phase=binding`. Bao gồm open/close scenario, start/end call, run_turn và request hook bị lỗi/timeout. Exact coverage: thiếu/trùng/unknown không được bỏ; cùng receipt ID không được tính hai lần trong config. Một receipt cho một index; receipt không được gộp nhiều hooks rồi cộng thêm turn usage lần nữa.

Mỗi receipt JSON có đúng các keys:

| Key | Ý nghĩa / kiểm |
| --- | --- |
| receipt_id | Nonempty ID, duy nhất trong config |
| request_sha256 | `extractor.digest(raw_records[raw_index])`, bind đúng yêu cầu/context/phase |
| cost_scope | `hook_runtime`; bao phủ chi phí Agent của hook, gồm tác vụ con/refresh được phân bổ không trùng |
| reconciled | Boolean; false giữ `USAGE_RECONCILIATION_PENDING`, không suy timeout miễn phí |
| pricing_sha256 | digest(policy.prices) pin trong manifest.sources trước execution |
| currency | Khớp currency policy, không FX tự động |
| cost | Finite number≥0, đối chiếu recompute theo giá pin |
| input_tokens/output_tokens | Integers≥0, không thiếu/bool |
| cost_units | Đúng3keys: asr (phút audio≥0), tts (số ký tự integer≥0), tool (số invocation integer≥0) |

Các component giá `not_used` bắt buộc units0. Price/currency chưa biết → INCOMPLETE, không fake free compute. Chi phí harness judge/extractor/simulator không nằm trong receipt Agent. Binding receipt bao phủ khởi tạo adapter; runtime/provider phải phân bổ đầy đủ charge ngoài lượt vào hook/binding phù hợp và khai reconciled chỉ khi hoàn tất billing. **Importer không tự lấy billing provider, không xác minh chữ ký hóa đơn, không đo compute local**: producer/deployment phải cung cấp dữ liệu thực; fixtures receipts chỉ là tests.

Khi đủ ledger, P6 tính cost/tokens từ **toàn bộ receipts**, không yêu cầu turn lỗi phải có TimingEvidence hoàn chỉnh. Cost của failed call ở tử số; denominator vẫn chỉ completed lifecycle +after-call barrier. Ledger không đổi completion hoặc chất lượng; missing trace/timing và FAIL P4 vẫn giữ. Completed0 → UNDEFINED. Không có ledger, legacy run_turn scope còn giữ ceiling failed-hook chưa reconcile.

## 2. Casebook review

File `casebook-review.json` có đúng5keys:

- `schema_version`: `p6-casebook-review-v1`.
- `run_id`: source manifest run.
- `reviewed_by`: người review, nonempty; là khai báo, **không chứng nhận quyền release**.
- `source_score_ref`: whole AssetRef đúng `score-report.json` source P4, relative tới P4 root, exact hash.
- `records`: list ErrorRecord theo schema hiện có.

Records phải lấy từ errors P6 đã triage: không trùng/unknown error_id; giữ nguyên run/context/category/expected/observed/source_split/learning_permission. Review không được biến deny/pending thành allow học. Root cause/remediation phải nonempty, evidence_refs có refs/hash thật relative root review; retest_ref phải whole SupplementalReport trong một **closed P4 retest run** nằm trong bundle review.

Importer kiểm retest: run ID khác source; manifest/run/report/trace IDs nhất quán; raw runner mang đúng run mới; trace có reviewed scenario/call/config; refs của checks tồn tại/hash đúng. Fixture retest không qualify lỗi real. Retest có thể vẫn FAIL—casebook ghi việc đã kiểm lại, không tự tuyên bố remediation thành công hoặc đổi lỗi original thành PASS.

Số qualifying = các scenario/call độc lập đã review có retest, chỉ khi source không phải fixture. Full/base của cùng call không nhân quota; fixture luôn0. Quota≥10 mới analysis_complete=true. Records chưa review vẫn giữ triage; thiếu quota INCOMPLETE. Không tự sinh phân tích, không auto-learn/Growth/active. Reviewer authority và approval release thuộc P7, không dùng reviewed_by thay thế.

## 3. Giới hạn còn lại

L04/L08 đã có importer/validation; **measurement thực vẫn OPEN** vì chưa có producer billing/runtime, ≥10 lỗi real và human review/retest thật. Source P3/P4 issues không bị xóa bởi sidecar mới. Timing-repeat cohorts vẫn chưa implement (chỉ cần khi chọn repeat protocol), fixture không đủ quota latency và giá pin example vẫn null.
