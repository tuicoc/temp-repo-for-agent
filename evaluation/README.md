# Evaluation — lối vào cho người tiếp tục code

Source sản phẩm ở `../backend/` và `../frontend/` chưa nhận các thay đổi evaluation; code tích hợp cũ được giữ dưới [product-integration-reference](product-integration-reference/README.md) để port có chọn lọc. Xem [CODE-HANDOFF](CODE-HANDOFF.md) trước khi chạy adapter sản phẩm.

Đọc theo thứ tự: [CODE-HANDOFF](CODE-HANDOFF.md) → [thiết kế sản phẩm hiện hành](../docs/design.md) và [flow cũ dùng khi phát triển evaluator](temp-repo-for-agent/docs/flow.md) → [flow evaluation](evaluation-flow.md) → [contract matrix](evaluation-contracts/schema-contract-matrix.md) → [trạng thái kiến trúc](architecture-status.md) và [giới hạn](LIMITATIONS.md). Chỉ đọc [kế hoạch P0–P10](evaluation-implementation-plan.md) khi cần tra gate/đầu ra của một phase; checkpoint trong plan là lịch sử, không phải kết quả hiện hành.

Code evaluator ở `eval_harness/`, CLI ở `run_eval.py`, `run_product_full.py`, `run_m2_rag.py`; adapter sản phẩm ở `product_adapter.py`. Code agent/runtime tích hợp cũ ở bản tham chiếu, chưa nằm trong source sản phẩm active. Bộ 5 scenario hiện tại là `datasets/output1-btc-diagnostic-v1/` và chỉ có giá trị **diagnostic** vì GT chưa được QA duyệt. ASR chưa nằm trong lượt chấm JSON hiện tại; khi làm ASR, đọc [ASR README](asr/README.md).

Giữ nguyên `BTC-Data-Vong1-TEAMS/`, JSON trong `output (1)/`, `evaluation-contracts/sources/` và dataset revision đã pin. Nhánh bàn giao này không mang `integration/`, `runs/`, tests, ASR audio hay model weights; chúng không được xóa ở máy gốc nhưng không phải phần source push. Không sửa nguồn/hash lock để làm đẹp kết quả; tạo revision/run mới. Không dùng test offline để tuyên bố đạt M1/M2.

Prompt agent: [ma trận](agent-prompt-coverage.md). Evidence P6: [protocol](p6-input-evidence.md). Cơ chế cải tiến M2 được chọn: [Reflection/Playbook](reflection-ab-design.md). Các thiết kế cũ không được chọn đã bỏ khỏi lối đọc chính.
