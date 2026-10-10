# Lỗi đã gặp và guardrail trước khi sửa evaluation

Đọc file này **trước khi sửa code trong `evaluation/`**. Đây là ledger từ run diagnostic `20261010-173702` và các lần sửa sau đó, không phải danh sách lỗi mới nhất của product. Luôn đối chiếu run mới theo `scenario_id / call / turn` trước khi kết luận lỗi còn tồn tại.

## 1. Các lỗi/bẫy đã gặp

| Vấn đề và bằng chứng | Tình trạng / điều cần nhớ |
| --- | --- |
| `BRIEF_WRONG_PROFILE`, `BRIEF_MISSING` trong run cũ | Evaluator từng chấm sai số điện thoại đã mask và đòi Call Brief khi khách chưa xác định danh tính; phần kiểm evaluation đã được chỉnh. Với lỗi mới, xem `brief-evidence.jsonl` và raw record trước khi quy cho product. Không bỏ kiểm profile để làm điểm đẹp. |
| `FACT_VALUE_WRONG_OR_UNUSED` cho `order_id`/`tracking` | Mã lỗi gộp *sai giá trị* và *không dùng*. Truy chuỗi `after_call` ghi fact → memory retrieval → Call Brief → câu trả lời/tool args ở call sau. Không tự sửa GT hoặc coi mọi ca là lỗi retrieval. Tracking của SCN-GEN-0002/call_2 vẫn bắt buộc. |
| `CLAIM_VALUE_WRONG` khi tên rút gọn hoặc “đang giao” khác mã `shipping` | So chuỗi có thể tạo false positive. `claim-adjudication.json` chỉ đánh dấu tương đương khi có catalog/tool xác nhận; trường hợp còn lại để QA xem. Không âm thầm đổi scorer BTC/GT. |
| `TOOL_BUSINESS_ERROR` ở baseline SCN-GEN-0001/call_1 | Agent đã thử SKU tự chế `AP-X`/`AIRPURE-X` thay vì SKU catalog `SKU-AP-X`; mock trả `unknown_sku`. Đây là lỗi đầu vào product; lần retry đúng SKU không xóa lỗi cũ. Tool-Call Accuracy và tool execution phải báo riêng. |
| `TOOL_EXPECTATIONS_NOT_LABELLED` / TCA không có số | Đã thêm nhãn tool cho 5 scenario, 12 call, cả full/baseline. Call không có positive tool không có nghĩa cấm mọi tool; TCA có thể `UNDEFINED`. Khi thêm case, cập nhật `tool_expectations.py`, grading cho hai config và test trước model. Xem [quyết định nhãn](TOOL-CALL-LABELS.md). |
| `must_say_any` làm TSR phụ thuộc cụm từ | v2 chỉ bổ sung các cách nói đã được chủ project duyệt cho 0003–0005; đây vẫn là assertion khớp chuỗi, **không** phải đánh giá ngữ nghĩa. Phân biệt thay đổi nhãn với cải thiện agent; không sửa điều kiện sau khi nhìn điểm run. |
| `USAGE_MISSING`, `EXTRACTOR_AUDIT_PENDING` | Thiếu bằng chứng thì báo `INCOMPLETE`, không điền 0/PASS hoặc tự suy chi phí. Audit extractor trước khi dùng nhãn question/claim/fact_usage làm kết luận chính thức. |
| Lời giá không có quote, claim lịch sử khi danh tính mơ hồ, hỏi tên lặp lại | Là các vấn đề product ghi trong bàn giao local cho thầy; **không sửa backend của thầy trong task evaluation**. Giữ trace và ghi test hồi quy/đề xuất riêng. |
| FAQ/growth case đã tạo nhưng agent chưa dùng | `gap-publish` chỉ tạo candidate; không chứng minh KB active đã nhận FAQ. Cần log FAQ ID/version được agent truy xuất ở R1. Không gọi một file `faq.md` là vòng cải tiến end-to-end. |

## 2. Guardrail bắt buộc trước và trong khi code

1. **Xác định phạm vi và quyền sở hữu.** Sửa `evaluation/` cho evaluator/dataset. Việc đụng `backend/` hoặc `temp-repo-for-agent/backend/` là product của thầy: ghi bàn giao hoặc xin quyết định riêng. Không sửa `evaluation-contracts/sources/btc/`, `BTC-Data-Vong1-TEAMS/`, `output (1)/`, revision dataset/run đã pin để tăng điểm. Không push file bàn giao riêng cho thầy.
2. **Đọc dữ liệu gốc trước khi sửa nhãn.** Nếu đổi scenario, GT, grading hoặc thêm case, dùng [`ground-truth-review/SKILL.md`](../datasets/ground-truth-review/SKILL.md); ghi nguồn, giá trị cũ/mới, bằng chứng, người duyệt, trạng thái. Tạo revision mới; QA agent/model không tự duyệt nhãn của mình. Case mới phải khai báo `assertion_only` hay judge/hybrid và tool labels cho mọi call trước khi chạy model.
3. **Giữ phép đo công bằng.** Full/baseline cùng scenario, prompt/model/tools/KB và kế hoạch call; chỉ `memory_read_previous` khác. R0/R1 dùng cùng frozen cohort, GT, rubric; growth set báo riêng. Không lấy đáp án/transcript frozen/golden để viết FAQ, playbook hoặc exemplar. Nhãn/chính sách đổi thì báo như một thí nghiệm khác, không cộng vào delta agent.
4. **Không suy bằng chứng.** Đọc `evidence/full.jsonl`/`baseline.jsonl` theo turn, `tools.jsonl`, `memory.jsonl`, `brief-evidence.jsonl`, `scored/validation.json`, `official-report.json` và `assertion-details.json`. Một mã lỗi chỉ là dấu hiệu; tách agent violation, thiếu evidence, schema/infra và tranh chấp GT. Lời agent nói “đã tạo đơn” không thay được `order.create` + state audit; `overall_pass` trong `output (1)/judgments/` không phải nhãn người của run agent.
5. **Bảo vệ dữ liệu khách và chính sách.** Không đưa PII, trạng thái đơn riêng, giá/KM/tồn kho tức thời vào FAQ/playbook tĩnh hoặc exemplar. Không lộ memory của người dùng chung SĐT trước xác minh; không dùng lịch sử cũ như sự thật hiện tại nếu chưa refresh qua tool. Không in secret/`.env` vào log hoặc commit.
6. **Preflight offline trước model.** Kiểm schema/provenance, test, nhãn full/baseline và `execution_gate.allowed` bằng `prepare()`/preflight. `evaluate` gọi model/API và tạo run mới, không dùng làm phép thử cấu hình. Run đã đóng là bằng chứng bất biến; không sửa tay file JSONL/JSON trong `runs/` rồi chấm lại như run thật.

## 3. Checklist hoàn thành một thay đổi

- Nêu lỗi ở `scenario/call/turn`, file evidence và giả thuyết root cause; phân biệt thay đổi evaluator với product.
- Kiểm mọi caller/schema/test bị ảnh hưởng; sửa tối thiểu và thêm test cho logic mới. Từ thư mục `evaluation/`: `../backend/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` (source-only checkout cần một interpreter có dependency, không bắt buộc venv nằm trong repo).
- Với dữ liệu mới: chạy gate trong skill, giữ bản gốc và reviewer decision. Với model run: ghi run ID/path, chi phí/usage nếu có, status `COMPLETE` hay `INCOMPLETE`, và so đúng cohort.
- Nếu lỗi vẫn thuộc product/QA hoặc thiếu authority/evidence, ghi rõ blocker; không biến code evaluation thành “fix” che lỗi.
