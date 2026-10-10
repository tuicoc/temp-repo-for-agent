# Trạng thái code evaluation trên nhánh `dai`

Chỉ có một kiến trúc product đang dùng: [`docs/design.md`](../docs/design.md), agent/hot/cold pipeline và MCP ở `../backend/src/`. Không dựng product architecture thứ hai trong `evaluation/`.

| Phần | Điểm vào | Trạng thái |
| --- | --- | --- |
| Chạy 5 scenario M2 | `run_eval.py evaluate` → `product.py` → `product_adapter.py` → `backend/src/pipeline/eval/bridge.py` | Đã nối agent thật, chạy full/baseline trên cùng case, tạo run mới; kết quả diagnostic, chưa phải nghiệm thu BTC. |
| Thu và chấm | `eval_harness/collector.py`, `scoring.py` | Ghi trace từng turn, tool, memory, Call Brief; gọi scorer BTC và xuất validation/chi tiết assertion. Thiếu evidence vẫn `INCOMPLETE`. |
| Nhãn/dataset | `datasets/output1-btc-diagnostic-v2/`, `tool_expectations.py`, `docs/TOOL-CALL-LABELS.md` | 5 scenario/12 call; tool labels cho cả full/baseline. GT chưa được QA duyệt toàn bộ. |
| Test và lịch sử | `tests/`, `run_eval.py history` | Unit tests offline và bảng chỉ mục run; run lịch sử không nằm trong Git. |
| M1, R0/R1 và M2 khác | `eval_harness/benchmark.py`, `rounds.py`, `judging.py`, `suite_bundle.py` | Có hợp đồng/component; `evaluate` hiện không chạy judge hoặc thí nghiệm cải tiến R0→R1 end-to-end. |
| Knowledge Gap / Reflection / Exemplar | `docs/flows/` | Luồng thiết kế và phần evaluation; cần product nối KB/feedback thực. Exemplar đang hoãn. |

Các lệnh chính và vị trí báo cáo: [README](README.md). Khi thêm dữ liệu hoặc nhãn, đọc [`ground-truth-review/SKILL.md`](datasets/ground-truth-review/SKILL.md) và chạy kiểm tra không gọi model trước. Bảo toàn `evaluation-contracts/sources/btc/`, `BTC-Data-Vong1-TEAMS/`, `output (1)/`, các revision dataset đã pin và run lịch sử. Hai bản BTC được giữ vì contract khóa nguồn và harness có đường dẫn bảo vệ cho cả hai; không gộp/xóa để dọn cây thư mục.

File bàn giao riêng cho thầy không được push theo yêu cầu chủ repo. Đừng thêm link trong Git tới file local đó.
