# Yêu cầu dataset để chạy và chứng minh vòng cải tiến

Tài liệu bàn giao cho người tạo dataset. **Không huấn luyện/fine-tune model.** Cải tiến chỉ được thay đổi memory, KB/FAQ, prompt/playbook hoặc điều phối; mỗi thay đổi phải có feedback và bằng chứng sử dụng ở R1. Đọc [`ground-truth-review/SKILL.md`](../datasets/ground-truth-review/SKILL.md) trước khi thêm case/nhãn.

## 1. Số lượng: yêu cầu đề và mục tiêu thử nghiệm là hai việc khác nhau

| Mục | Ngưỡng/đề xuất | Ghi chú |
| --- | ---: | --- |
| Scenario của dataset M2 | **40** theo báo cáo kiểm dữ liệu `output (1)` | Hiện có 5/40; tạo mới không đồng nghĩa đã được QA duyệt. |
| Hội thoại transcript / audio M2 | **250 / 100**, audio **≥3 giờ**, noisy **≥20%** theo báo cáo đó | Đây là chỉ tiêu toàn dataset, **không phải** 250 case cho phép so R0/R1. |
| Khách đa phiên / đa kênh | **60 / 30** theo báo cáo đó | Cần ID khách ổn định và nhiều call/channel có nguồn. |
| Lĩnh vực / cặp lĩnh vực–vùng / SKU | **3 / 9 / ≥100** theo báo cáo đó | Đối chiếu catalog và policy BTC. |
| Nhãn người cho judge agreement | **≥20 cặp `(call, criterion)`** theo rubric BTC | Người chấm độc lập; không tính 5 file `output (1)/judgments/` là nhãn người. |
| Vòng cải tiến tối thiểu | **R0 và R1**, cùng một frozen set | Không có ngưỡng số scenario riêng chỉ cho hai vòng; chọn bộ đủ phủ tình huống định cải tiến. |
| Bộ thử nhanh đề xuất | **5 scenario hiện có + 3–5 case mới theo cơ chế**, nếu cần | Chỉ là mục tiêu diagnostic nhỏ, **không thay** ngưỡng M2 hay bằng chứng thống kê. |

Nguồn ngưỡng toàn dataset: [`output (1)/reports/validation_report.md`](<../output (1)/reports/validation_report.md>); chuẩn rubric và so chéo: [`DIEU-CHINH-DE.md`](../evaluation-contracts/sources/btc/DIEU-CHINH-DE.md), [`llm_judge_rubric.json`](../evaluation-contracts/sources/btc/eval/llm_judge_rubric.json). Bộ test ẩn 41 scenario của BTC **không phải** số case team phải tự tạo.

## 2. Mỗi scenario/call phải giao những nhãn gì

Theo `evaluation-contracts/sources/btc/schemas/scenario_format.md`, xuất scenario JSON có `scenario_id`, `level`, persona, khách/định danh, 2–3 call đa lượt nếu kiểm memory, `customer_turns`, ngày/kênh, `facts_established`, `must_carry_over`, `must_not_ask`, `ground_truth_facts`, `expected_outcome`, `success_if`. Fact giá, KM, tồn kho, đơn hàng phải khớp catalog, policy và mock BTC đúng ngày; không lấy lời model sinh làm ground truth.

Giao thêm **phiếu nhãn chấm** cho *từng call* (trong grading contract hoặc bảng review đi kèm):

| Trường cần chốt | Nội dung |
| --- | --- |
| `tsr_method` | `assertion_only` hoặc `judge`/`hybrid`; nêu điều kiện nào thật sự quyết định TSR, điều kiện nào chỉ để chẩn đoán. Hiện `evaluate` cho 5 case chỉ thực thi `assertion_only`; chọn judge/hybrid đòi nối evaluator trước khi chạy. |
| Assertion | Tool bắt buộc + đối số + kết quả/trạng thái cần xác minh; tool cấm; điều kiện nói/không nói; nguồn evidence. `must_say_any` chỉ là khớp chuỗi, không phải hiểu ngữ nghĩa. Thiếu evidence ⇒ `INCOMPLETE`, không PASS/FAIL giả. |
| Judge, nếu áp dụng | ID J01–J12 của rubric BTC, điều kiện áp dụng, PASS/FAIL, transcript/GT đưa vào prompt, câu trích dẫn từ lời agent; chỉ rõ judge có quyết định hybrid TSR không. |
| Tool-Call Accuracy | Positive, forbidden, conditional và read-only allowance cho **mọi call**, kể cả call không có tool bắt buộc; cùng kỳ vọng cho full/baseline. |
| Provenance/QA | Nguồn field/claim, reviewer, quyết định duyệt, tranh chấp, phiên bản/hash; tự chấm của QaAgent chỉ là đề xuất. |

Với 5 case hiện tại: 0001–0002 chấm tool/đối số; 0003 có kiểm tồn kho + không tạo đơn + lời giải thích; 0004–0005 có xác nhận danh tính + cấm tool đơn hàng. Cả 5 đang là **diagnostic assertion**, chưa phải nhãn judge của run agent hoặc golden được duyệt toàn bộ. Khi thêm case, cập nhật `tool_expectations.py`, test coverage và chạy `product.prepare()`/preflight **không gọi model** theo skill trước khi `evaluate`.

## 3. Tách dữ liệu cho vòng cải tiến

| Tập | Lấy từ đâu | Được dùng để làm gì |
| --- | --- | --- |
| **Nguồn feedback/development** | Cuộc gọi/consultant/QA có provenance, **ngoài frozen set** | Tìm gap, rút lesson, sửa memory/prompt, biên soạn FAQ/playbook; có thể mở rộng. |
| **Frozen evaluation set** | Một phiên bản scenario + GT + grading được ghim trước R0 | Chạy R0 và R1 **nguyên bộ, nguyên nhãn, nguyên điều kiện chấm**; chỉ thay đúng thành phần cải tiến đã khai báo. Không dùng đáp án/transcript của nó để viết FAQ, playbook hay few-shot. |
| **Golden set** | Phần frozen đã được người duyệt GT độc lập | Dùng báo kết quả đáng tin; 5 case hiện tại có thể frozen cho diagnostic nhưng chưa thành golden chính thức. |
| **Growth set** | Case mới phát sinh từ feedback đã duyệt | Kiểm lỗi có tái phạm; báo riêng, không thêm vào mẫu số R1 nếu R0 chưa chạy case đó. |

Tối thiểu trong hồ sơ hai vòng: ID/hash frozen set và grading giống nhau; R0 trace/điểm; feedback ID + nguồn độc lập; quyết định duyệt; diff/hash KB/prompt/memory R1; log chứng minh agent thật sự đọc phiên bản mới; R1 trace/điểm; bảng full/baseline và delta R0→R1, nêu `INCOMPLETE` khi thiếu evidence hoặc cohort lệch. **Không chọn thay đổi sau khi nhìn đáp án frozen set rồi đưa đáp án vào R1.**

## 4. Case cần có theo từng cơ chế

Đây là **phân bổ đề xuất để bắt đầu**, không phải ngưỡng BTC. Các nhóm có thể chồng nhau nhưng mỗi case phải có `mechanism_target` rõ. Nên giao theo cặp *trước/sau cùng tình huống* và ít nhất một negative/safety case; không nhân số case máy móc nếu cùng một scenario đã kiểm nhiều điều kiện.

| Cơ chế | Case development/feedback tối thiểu để thử | Case frozen cần phủ và nhãn cần có |
| --- | --- | --- |
| **Memory** | 1 call tạo fact và call sau cần dùng; 1 biến thể fact đổi/TTL hoặc chung SĐT | Đề xuất **3–5 scenario đa phiên**: dùng đúng fact, không hỏi lại, không lộ nhầm hồ sơ. Gắn `must_carry_over`, `memory_expectation`, identity, nguồn fact và expected tool/answer. R1 phải đổi đúng quy tắc memory, không đổi GT. |
| **Knowledge Gap → FAQ** | Ít nhất **1 gap thật** ngoài frozen: câu hỏi, câu consultant trả lời, nguồn chính sách, quyết định lưu/revoke | Đề xuất **3–5 case**: hỏi được FAQ mới, câu hỏi tương đương, câu ngoài phạm vi/riêng tư không trả lời bằng FAQ. Gắn FAQ ID/version, expected grounding/abstention, judge nếu chất lượng giải thích quyết định đạt. Growth case từ gap báo riêng. |
| **Reflection → playbook** | Nhiều cuộc độc lập cùng `situation`, có **thắng sạch và không thắng** để đối chiếu; không suy luận từ 1 cuộc | Đề xuất **3–5 case** cùng tình huống và một case khác để kiểm không áp dụng nhầm. Gắn `situation`, verified outcome, hành vi `when/do/dont`, playbook ID/version đã đưa vào context, guardrail và TSR. Chưa đủ bằng chứng hai phía thì chỉ tạo lesson candidate. |
| **Exemplar Bank** | Theo thiết kế hiện tại: đề xuất **≥3 thắng sạch + ≥2 không chốt** cùng tình huống, từ cuộc/khách độc lập; QA chọn 2 exemplar sạch, độc lập với playbook | Case 0/1/2 mẫu và tình huống không khớp; log **hai** exemplar ID thực sự vào context mới gọi là few-shot. Không tuyển mẫu từ frozen/golden. Xem [luồng Exemplar](flows/EXEMPLAR-BANK-FLOW.md). |

**Feedback tối thiểu theo yêu cầu M1:** thu ít nhất **2 loại nguồn** trong: outcome cuộc gọi, điểm evaluator, 👍/👎 trên gợi ý, hoặc khách phải nhắc lại thông tin. Dataset nên có `feedback_type`, `source_call_id/turn_id`, thời gian, người/nguồn chấm và evidence ref; không đánh đồng “khách từ chối” với “agent không biết”.

## 5. Bàn giao và trạng thái hiện tại

Người tạo dataset bàn giao: scenario/conversation/feedback tách theo tập; phiếu nhãn từng call; tài liệu nguồn và quyết định QA; manifest ID/hash; danh sách case nào đo memory/FAQ/playbook; ít nhất 20 cặp nhãn người–judge nếu sẽ báo agreement. Không sửa `output (1)`, nguồn BTC hay run cũ; mọi chỉnh nhãn ra revision mới.

Đặt mỗi revision trong `evaluation/datasets/<set-id>/scenarios/*.json`, rồi khai báo một set ở `evaluation/datasets/registry.json` với `id`, `split`, `path`, `status`, `reviewed_by`. Set `approved` cần thêm `tool_labels` và `gt_review` trỏ tới hai JSON trong cùng gốc `datasets/`. `tool_labels` ánh xạ `scenario_id → call_id → [{"name", "args_match", "required"}]`; call không có positive tool dùng `[]`. `gt_review` ánh xạ `scenario_id → call_id → {"status":"approved", "reviewed_by":"<cùng reviewer của set>", "source":"<BTC policy/catalog/mock + ngày/phiên bản>", "decision":"<lý do duyệt GT và success_if>"}`. Đây là phiếu xác nhận; người duyệt phải thật sự kiểm từng fact và điều kiện với nguồn, không điền văn mẫu để qua gate.

Chạy `../backend/.venv/bin/python run_eval.py data-check --set <set-id>` từ `evaluation/`. Lệnh kiểm schema Scenario, ID/trùng nội dung, call coverage của nhãn tool và GT review, `success_if`/tool label, input adapter chưa hỗ trợ và trạng thái duyệt. Sửa dữ liệu đầu vào theo mã lỗi, tạo revision mới nếu revision cũ đã dùng. Sau khi gate đạt, gọi `product.prepare()` trong thư mục tạm để kiểm offline cả full/baseline, provenance và manifest. `evaluate --dataset-id <set-id>` mới gọi agent/model. BTC golden set chưa được công bố: khi nhận, lưu nguyên bản riêng, lập revision tương thích có đối chiếu từng field/call; nếu schema hoặc điều kiện chấm BTC mới khác contract hiện tại, cập nhật adapter/contract và test trước khi chạy, không ép nhãn hoặc bỏ field để làm gate xanh.

`product.evaluate` nay nhận set đã duyệt qua `--dataset-id`, không còn khóa 5 case; đường mặc định vẫn dùng 5 case diagnostic. Đường này hiện sinh grading `assertion_only`. Case cần judge/hybrid chỉ được chạy sau khi evaluator hỗ trợ và được kiểm thử. GT review trong registry là lời xác nhận của người duyệt, không thể được code tự chứng minh đúng nghiệp vụ. FAQ/playbook/exemplar được agent dùng ở R1 vẫn cần evidence product và hai run thật trước khi tuyên bố vòng cải tiến end-to-end.
