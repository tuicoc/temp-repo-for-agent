# Trạng thái triển khai so với `temp-repo-for-agent/docs/flow.md`

**Trạng thái checkout hiện tại:** nhánh `dai` bắt đầu từ `origin/main` (`be8e85e`). Bảng dưới là trạng thái code tích hợp trong [product-integration-reference](product-integration-reference/README.md), **không phải** các module đang active trong source sản phẩm. Evaluator không thể chạy đường tích hợp đó trước khi port lại.

`flow.md` là chuẩn thiết kế; các mục dưới đây mô tả **code đã chạy**, không thay thế tiêu chí nghiệm thu BTC. BTC source, dataset và run đã đóng giữ nguyên.

| Nhịp | Đã nối | Còn thiếu để gọi đúng `flow.md` |
|---|---|---|
| Hot path | FastAPI/React và evaluator dùng `CallRuntime`; resolve/brief, router luật kể cả CONTINUITY, Advisor/tool, hard guard so giá chính xác theo tool hiện tại và Policy opt-in (tối đa một repair an toàn); working turns được lưu. Business tools và đọc memory đi qua FastMCP nội bộ cùng process. | `HotState` LangGraph checkpointer, MCP process/role isolation đầy đủ, copilot `interrupt/Command`, khôi phục call mở sau restart, xử lý ASR/realtime. |
| Cold memory | `end_call` tạo job `persist`, trích từ turn đã lưu, kiểm toàn bộ proposal trước khi ghi, gate span/PII/type, ghi facts và episode; evaluator chờ barrier. Có polling worker opt-in cho web. | Quyền `memory_writer` qua MCP, schema ontology/TTL/disputed đầy đủ, kiểm recovery khi DB lỗi giữa các bước ghi. Web `end_call` vẫn chờ xử lý đồng bộ. |
| Cold QA | QaAgent/Policy có prompt và schema; verdict QA có bảng riêng, lỗi giữ `UNDETERMINED`; bundle có flag và tiêu chí BTC đã pin (J01 call 2+, J02/J06/J08 mọi call); BTC evaluator có selector/judge độc lập. | Bật theo run có ngân sách và đầy đủ applicability J01–J12; QA human agreement ≥20 cặp, evidence pool/threshold và Reflection consumption tự động. |
| Knowledge Gap | Signal, candidate có nguồn, hash/approval QA, R0/R1 diagnostic và phiên bản sandbox được pin. | Job collect/cluster/apply/rollback tổng quát; FAQ active version cho mọi cuộc; growth/frozen gate chính thức. |
| M2 RAG/Simulator/Reflection | Có producer/evaluator và test hợp đồng riêng. | MCP knowledge retriever trong hot path, simulator model thật theo ba seed, playbook active/revocable và ablation nối Advisor. |

Không gọi phần còn thiếu là đã hoàn tất chỉ vì đã có class hoặc import. Trước lần dọn bàn giao, product PostgreSQL sandbox đạt 70 tests; sau thay đổi MCP memory, chỉ có 17 unit tests đạt. Lượt kiểm lại PostgreSQL bị môi trường sandbox chặn khởi động daemon và chưa hoàn tất; chưa có live model run mới.
