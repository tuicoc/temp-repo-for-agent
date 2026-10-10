# Evaluation — code đang dùng

Đọc [CODE-HANDOFF.md](CODE-HANDOFF.md) trước khi sửa code. Kiến trúc sản phẩm hiện hành ở [docs/design.md](../docs/design.md); agent, hot/cold pipeline và MCP đang ở `../backend/src/`. Folder này chứa evaluator/contract/dataset, **không chứa một bản product architecture thứ hai**.

Điểm vào: `run_eval.py` → `eval_harness/__main__.py`. Code chấm ở `eval_harness/`; [đề bài](requirements/project-brief.pdf) và contract/nguồn BTC pin ở `evaluation-contracts/`; dữ liệu JSON 5 scenario hiện dùng ở `datasets/output1-btc-diagnostic-v2/` (quyết định duyệt tại [review-decisions.md](datasets/output1-btc-diagnostic-v2/review-decisions.md)), nguồn bất biến ở `output (1)/` và revision v1 được giữ nguyên.

Thư mục chính: `eval_harness/` là code chấm; `datasets/` là các revision; `tests/` là kiểm tra offline; `docs/` là yêu cầu dataset, nhãn và luồng cải tiến; `evaluation-contracts/` là contract và BTC được pin. `BTC-Data-Vong1-TEAMS/` là bản BTC gốc được giữ nguyên cho các đường dẫn bảo vệ cũ, không phải bộ test thứ hai. `runs/` là output local theo từng lần chạy và không đưa lên Git.

Khi thêm hoặc sửa dữ liệu/ground truth, đọc [skill duyệt GT](datasets/ground-truth-review/SKILL.md) trước. `AGENTS.md` trong folder này nhắc lại quy tắc đó cho những lần làm việc sau.

Bộ source-only này có unit tests trong `tests/`, nhưng không kèm run lịch sử, ASR audio/model hay virtualenv.

## Running the team's agent

One command, from the repository root:

```sh
backend/.venv/bin/python evaluation/run_eval.py evaluate
```

`evaluate` (in `product.py`) pins the inputs, runs the agent through `run_fixed` with `product_adapter.py` (which starts `../backend/src/pipeline/eval/bridge.py`; business tools come back to this harness's mock), collects with `extractor-prompt.txt` through `../backend/src/pipeline/eval/extract_command.py`, and scores with the organisers' grader and this harness's checks.

Output: `runs/<date-time>/` (or `--out`), with `inputs/`, `raw/`, `evidence/` and `scored/`; the table is `scored/scorer.stdout.txt`, the summary `execution-report.json`. The root README, Getting started section 5, says what each folder holds. P6 (`report`) is not run: it implements level M1 and these scenarios are M2.

Mỗi run mới tạo nhãn Tool-Call Accuracy cho đủ 5 scenario ở `inputs/expected-tools/` và chấm cùng nhãn cho full/baseline. Xem [nhãn tool](docs/TOOL-CALL-LABELS.md) để biết từng kỳ vọng, giới hạn và trạng thái QA. Run cũ không bị chấm lại.

Xem log tổng hợp mọi lần chạy (kể cả lần lỗi hoặc thiếu bằng chứng), không gọi model/API:

```sh
backend/.venv/bin/python evaluation/run_eval.py history
```

Lệnh đọc trực tiếp `runs/*/execution-report.json` và `scored/official-report.json`, hiển thị số cuộc gọi, TSR/CCR/RQR baseline → hệ thống, trạng thái, nguyên nhân và đường dẫn báo cáo. Không tạo bản sao kết quả; mỗi thư mục run là log gốc. Chỉ số trong bảng này vẫn là diagnostic, không phải chứng nhận M1.

Trong mỗi run mới, `scored/claim-adjudication.json` giải thích riêng các claim khác chuỗi GT: chỉ đánh dấu `EQUIVALENT` khi tên rút gọn khớp duy nhất với catalog trong trace hoặc lời “đang giao” được `order.status` xác nhận; còn lại là `NEEDS_REVIEW`. `scored/tool-business-error-review.json` liệt kê lỗi tool và lần gọi sau đã phục hồi nếu có. Hai báo cáo **không thay đổi** `official-report.json`, chỉ số BTC hay các lỗi trong `validation.json`.

## Knowledge Gap Loop trong evaluation

Xem [luồng Knowledge Gap](docs/flows/KNOWLEDGE-GAP-LOOP.md) để biết phần evaluation đã có và điểm nối product còn thiếu.

Mỗi lần `score` tạo `scored/knowledge-gap-candidates.json` từ các lượt `handoff.transfer` thành công **hoặc** agent nói rõ không có/không đủ thông tin ở cấu hình full. Đây là **danh sách cần duyệt**, không mặc định là thiếu FAQ: chuyển máy vì an toàn, thông tin đơn riêng, giá/tồn kho hiện thời hay khách từ chối không tạo FAQ chung. Nếu transcript có câu trả lời của consultant, file giữ nó làm bằng chứng; nếu chưa có thì phải bổ sung bằng chứng ngoài run trước khi duyệt. Không lấy outcome `từ chối` làm tín hiệu “agent không biết”.

Quét lại một run cũ mà không chạy model hay chấm lại BTC:

```sh
backend/.venv/bin/python evaluation/run_eval.py gap-scan \
  --run evaluation/runs/<run>/evidence --out /path/to/new-gap-candidates.json
```

Run `20261010-173702` cho 5 candidate từ lời agent nhận thiếu thông tin, 0 handoff thành công. Không duyệt cả 5 thành FAQ; từng ca cần phân loại `reusable_faq` / `dynamic_tool_or_identity` / `safety_handoff` / `product_bug`.

Người đã trả lời/QA xem từng gap, đối chiếu chính sách và nguồn sản phẩm, rồi tạo file review JSON với `gap_id`, `reviewer`, `decision: "approve_faq"`, `general_question`, `general_answer`, `evidence`, `policy_checked: true`, `consultant_answer_verified: true`, `must_say_any` (cụm từ do người duyệt chọn để chấm lại). Câu hỏi/đáp án phải là quy tắc dùng chung, không chứa dữ liệu khách, giá/tồn kho/trạng thái đơn tức thời hoặc tư vấn y tế vượt chính sách. Ví dụ cấu trúc ở [knowledge-gap-review.example.json](knowledge-gap-review.example.json).

```sh
backend/.venv/bin/python evaluation/run_eval.py gap-publish \
  --candidates evaluation/runs/<run>/scored/knowledge-gap-candidates.json \
  --review /path/to/review.json \
  --out evaluation/datasets/growth/<gap-id>-v1
```

Lệnh tạo thư mục mới, không ghi đè: `decision.json` giữ bằng chứng/người duyệt, `faq.md` là FAQ candidate, `growth-case.json` là ca regression thuộc growth set. Golden set và GT hiện hành không đổi. Phần evaluation **chưa** tự bật FAQ trong KB hay chạy growth case qua agent; cần product tích hợp `kb.upsert/search`, log/revoke và một adapter test phù hợp trước khi khẳng định vòng lặp end-to-end đã chạy. Khi thêm growth case vào suite chính, áp dụng quy trình duyệt GT ở trên và so R0/R1 cùng cohort.

Khi đã có câu trả lời agent cho các case growth, tạo JSON ánh xạ `case_id` → chuỗi câu trả lời và chấm tất cả case trong thư mục:

```sh
backend/.venv/bin/python evaluation/run_eval.py gap-check \
  --growth-root evaluation/datasets/growth --responses /path/to/agent-responses.json
```

`gap-check` chỉ kiểm tra cụm từ trong câu trả lời do bên chạy agent cung cấp; không tự xác minh provenance của file responses và không được xem là chứng nhận end-to-end.

## Reflection và playbook

Xem [luồng Reflection](docs/flows/REFLECTION-FLOW.md) để biết luồng từ QA chấm cuộc gọi đến playbook trong KB và cách evaluation kiểm chứng. [Luồng Exemplar](docs/flows/EXEMPLAR-BANK-FLOW.md) là thiết kế đang hoãn. [Yêu cầu dataset](docs/DATASET-REQUIREMENTS-FOR-IMPROVEMENT.md) phân biệt số lượng theo đề và số case thử nghiệm đề xuất.

## RAG Recall@3/@5 trên 60 câu BTC

`rag-recall` gọi đúng `kb_search` của backend (cần backend venv và DB/KB hoạt động), kiểm corpus policy của product khớp bản BTC đã pin, rồi lưu top-5 chunk ID và báo cáo retrieval:

```sh
backend/.venv/bin/python evaluation/run_eval.py rag-recall --out evaluation/runs/rag-<run-id> --on 2026-10-15
```

Lệnh không gọi LLM; `retrieval.json` giữ 60 kết quả, `report.json` giữ Recall@3/@5 và multi-hop full recall. Nếu thiếu câu, chunk ID sai hoặc corpus khác bản BTC, không xuất điểm. Đây là chẩn đoán retrieval; chưa chấm chất lượng câu trả lời, abstention hoặc chứng nhận version của toàn bộ KB lưu trong DB.
