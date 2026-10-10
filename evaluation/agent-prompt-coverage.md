# Agent/prompt coverage cho M1–M2

Nguồn chuẩn: `temp-repo-for-agent/docs/flow.md`, PDF đề gốc và BTC rubric đã khóa trong `evaluation/evaluation-contracts/sources/btc/`. Tài liệu này là ma trận triển khai, không phải nhãn nghiệm thu. Prompt của product nằm trong source snapshot và được hash-pin cùng bundle; full/baseline dùng cùng snapshot, chỉ khác quyền đọc memory phiên trước.

| Ca/yêu cầu | Agent và prompt | Quyết định kiểm bằng code | Kiểm offline |
|---|---|---|---|
| Tiếp nối đa phiên/đa kênh, khách đổi ý | Memory trích quote/span; Advisor dùng brief có quyền | `CallRuntime.snapshot`, identity gate, supersede, after-call barrier | `test_call_runtime.py` |
| Số dùng chung/chưa xác minh | Orchestrator chọn identity; Advisor hỏi xác nhận | Không đọc private memory, tool lane rỗng | `test_call_runtime.py`, `test_agent_contracts.py` |
| Giá/KM cũ, hết hàng, thiếu nguồn, lỗi tool | Advisor tra tool hiện tại; Policy kiểm cam kết mềm | `guard_reply`, business-event outcome, reconciliation barrier | `test_call_runtime.py`, `test_agent_contracts.py` |
| Chốt đơn, callback, handoff | Advisor xác nhận điều kiện; Orchestrator chọn lane | Bind tool theo lane, sự kiện ghi phải hoàn tất trước commit | `test_call_runtime.py`, public BTC contract tests |
| PII, AI honesty, ngoài phạm vi, ASR chưa rõ | Advisor không đoán; Policy hậu kiểm khi bật | Che PII trước model, hard guard trước Policy, fallback | `test_call_runtime.py`, `test_agent_contracts.py` |
| J01–J12 BTC | QA chấm một tiêu chí/lần sau call | Quote phải thuộc lời Agent; evaluator kiểm lại verdict, hard FAIL không bị đảo | `test_agent_contracts.py`, `evaluation/eval_harness/judging.py` |
| RAG có citation/quyền truy cập | Advisor dùng retrieval đã ghim, không có nguồn thì abstain | Catalog chunk/version và quyền nguồn của evaluator | `evaluation/eval_harness/rag_runner.py` tests |
| Reflection/Playbook | Bước đề xuất của QA, không thêm agent product | Evidence, hash/approval và release gate | `evaluation/eval_harness/reflection.py` tests |
| Simulator tám luật | CustomerSimulator evaluator-only | Patience/seed/oracle nằm trong kernel, Agent chỉ nhận lời khách | `evaluation/eval_harness/simulation.py` tests |

Policy và QA là feature flag M2 mặc định tắt trong bundle. QA chỉ chạy khi có `qa_criteria` được pin; nếu thiếu hoặc output sai, ghi `UNDETERMINED`, không tự tạo PASS. Public BTC samples chỉ kiểm contract, không nhập vào điểm năm scenario diagnostic. Chưa chạy model thật, ASR hay benchmark M2 trong revision này.
