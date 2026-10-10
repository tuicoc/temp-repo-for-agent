# Evaluation — code đang dùng

Đọc [CODE-HANDOFF.md](CODE-HANDOFF.md) trước khi sửa code. Kiến trúc sản phẩm hiện hành ở [docs/design.md](../docs/design.md); agent, hot/cold pipeline và MCP đang ở `../backend/src/`. Folder này chứa evaluator/contract/dataset, **không chứa một bản product architecture thứ hai**.

Điểm vào: `run_eval.py` → `eval_harness/__main__.py`. Code chấm ở `eval_harness/`; [đề bài](requirements/project-brief.pdf) và contract/nguồn BTC pin ở `evaluation-contracts/`; dữ liệu JSON 5 scenario ở `datasets/output1-btc-diagnostic-v1/` và nguồn `output (1)/`. Không sửa nguồn/GT đã pin; tạo revision mới.

Đường chạy end-to-end với product hiện hành **chưa nối**: `../backend/src/pipeline/eval/runner.py` còn `NotImplementedError`. Không coi preflight, fixture hoặc module import là kết quả M1/M2. Bộ source-only này không kèm unit tests, run lịch sử, ASR audio/model hay virtualenv theo yêu cầu bàn giao.
