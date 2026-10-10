# Bàn giao code evaluation trên nhánh `dai`

Chỉ có **một kiến trúc product đang dùng**: [docs/design.md](../docs/design.md), agent ở `../backend/src/agents/`, luồng hot/cold ở `../backend/src/pipeline/`, MCP ở `../backend/src/mcp/`. Không dùng flow, bridge hay prompt của kiến trúc cũ: chúng đã được xóa khỏi cây hiện tại và còn khôi phục được qua Git commit `6987aa3` nếu cần truy vết.

## Đã có trong `evaluation/`

| Mảng | Code chính | Trạng thái |
|---|---|---|
| Nguồn/contract BTC | `evaluation-contracts/`, `eval_harness/contracts.py`, `assets.py` | Checker khóa 46 source hashes, schema và fixture; không sửa BTC để đạt điểm. |
| Nhận input và chạy fixed-turn | `eval_harness/preflight.py`, `runner.py`, `environment.py` | Có preflight, full/baseline và mock tools theo adapter contract; **chưa có adapter tới product hiện hành**. |
| Trace và chấm | `eval_harness/collector.py`, `extractor.py`, `model_extractor.py`, `scoring.py`, `judging.py` | Thu/kiểm evidence và gọi scorer BTC; thiếu trace thật thì kết quả INCOMPLETE. |
| Dataset, ASR, metric M1 | `eval_harness/datasets.py`, `asr_suite.py`, `benchmark.py`, `metrics.py`, `reporting.py`, `p6_evidence.py`, `asr/` | Có registry/adapter, phép đo và báo cáo; gói push không kèm audio/runs, lượt 5 scenario trước mắt chỉ chấm JSON. |
| R0/R1 và M2 | `eval_harness/rounds.py`, `release.py`, `rag_corpus.py`, `rag_runner.py`, `rag_review.py`, `simulation.py`, `reflection.py`, `suite_bundle.py`, `package.py` | Có component/contract offline và recommendation; chưa đủ producer/evidence live để release hay nghiệm thu M2. |
| Dữ liệu 5 scenario | `normalize_output1.py`, `output (1)/`, `datasets/output1-btc-diagnostic-v1/` | 5 scenario, 12 call JSON dẫn xuất; GT do nhóm diễn giải, chờ QA duyệt, chỉ diagnostic. |

CLI chung: `run_eval.py`. Ví dụ contract check không gọi model: `python evaluation/evaluation-contracts/check_contracts.py` từ repo root sau khi cài requirements. Các command `preflight`, `run`, `collect`, `score`, `report`, `benchmark` cần đầu vào/adapter đã pin; không chạy API khi chưa có ngân sách và run mới.

## Việc cần code tiếp — đúng chỗ

1. Đọc `../backend/src/api/harness.py` và `../backend/src/pipeline/eval/runner.py`: runner product hiện còn stub. Chọn **một** adapter nối hooks `eval_harness/runner.py` với hot/cold path hiện hành; không dựng CallRuntime thứ hai.
2. Chạy 5 scenario cùng controls, full/baseline chỉ khác quyền đọc memory phiên trước; tách state, đợi after-call barrier và xuất tool/turn/memory evidence đúng schema.
3. Đưa evidence qua collector → scorer → report. Missing usage, GT chưa duyệt hay module chưa chạy phải là INCOMPLETE/UNDETERMINED, không điền 0/PASS.
4. Khi M1 functional chạy được mới nối M2 từng module theo `../docs/design.md` và contract BTC. Không coi code component hiện có là producer/live acceptance.

Giữ nguyên `evaluation-contracts/sources/btc/`, `BTC-Data-Vong1-TEAMS/`, `output (1)/` và revision dataset đã pin. Gói này cố ý không mang tests, historical runs, ASR audio/model hay môi trường cục bộ. Nếu cần kiểm hồi quy, viết lại test tối thiểu bên cạnh thay đổi mới; đừng sửa evidence cũ.
