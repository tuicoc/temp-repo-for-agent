# Bàn giao phần đã phát triển trong `evaluation/`

Cập nhật 10/10/2026. Tài liệu này ghi **code trong `evaluation/`**. Product trên nhánh `dai` bắt đầu từ `origin/main` tại `be8e85e`; mã tích hợp evaluation với product trước đó được giữ làm [bản tham chiếu](product-integration-reference/README.md), chưa áp dụng vào source product hiện hành. Muốn chạy lại đường tích hợp phải port có chọn lọc; không chép đè cả thư mục.

## Đọc trước khi code

1. `../docs/design.md` là thiết kế product hiện hành; `temp-repo-for-agent/docs/flow.md` là flow cũ dùng khi phát triển evaluator; `evaluation-flow.md` là flow chấm. Đối chiếu cả ba, không coi tài liệu cũ là code đang chạy.
2. `evaluation-contracts/schema-contract-matrix.md`, `report-schemas.md`, `harness-acceptance-tests.md`; BTC chuẩn được pin ở `evaluation-contracts/sources/btc/`.
3. Bảng code dưới đây, rồi `architecture-status.md` và `LIMITATIONS.md` để thấy phần còn thiếu. `evaluation-implementation-plan.md` chỉ dùng tra gate P0–P10.

## Code evaluator đang có

| Phần | File chính | Đã làm được | Giới hạn hiện tại |
|---|---|---|---|
| Contract/nguồn | `evaluation-contracts/check_contracts.py`, `eval_harness/contracts.py`, `assets.py` | Khóa hash nguồn BTC, kiểm schema/fixture và AssetRef; đọc đầu vào đã pin. | Không được sửa nguồn/lock để hợp kết quả. |
| P1 input | `eval_harness/preflight.py` | Kiểm manifest/scenario/controls trước khi chạy. | PASS preflight không phải chất lượng Agent PASS. |
| P2 runner | `eval_harness/runner.py`, `environment.py` | Fixed-turn full/baseline, tool sandbox BTC, raw run bất biến và barrier theo adapter contract. | Cần product adapter tương thích để chạy Agent thật; bản clone mới chưa có bridge cũ. |
| P3 collector | `eval_harness/collector.py`, `extractor.py`, `model_extractor.py` | Validate raw/evidence, trích facts/trace, audit và xuất BTC wire cohort. | Model extractor chỉ chạy khi cấu hình/chấp thuận API; không bịa evidence thiếu. |
| P4 scorer | `eval_harness/scoring.py`, `judging.py` | Gọi scorer BTC nguyên bản, thêm hard checks và chọn rubric/judge evidence. | Không có QA human labels đủ cỡ hoặc producer Judge live thì chưa nghiệm thu. |
| P5 dataset/ASR | `eval_harness/datasets.py`, `asr_suite.py`, `asr/` | Inventory dataset provisional, replay/infer ASR riêng, coverage/ITN/entity và lock cấu hình. | Lượt 5 scenario JSON hiện tại **không chấm ASR**; full BTC audio/validator vẫn deferred. |
| P6 báo cáo | `eval_harness/benchmark.py`, `metrics.py`, `reporting.py`, `p6_evidence.py` | Một pipeline P2→P6, tính full/baseline, latency/cost khi có evidence, nhập billing/casebook đã đóng. | Usage/timing/review thiếu phải INCOMPLETE; fixture không chứng minh ngưỡng M1. |
| P7 cải tiến | `eval_harness/rounds.py`, `release.py`, `prepare_product_pair.py` | So R0/R1 với controls, hash/approval/consumption/release recommendation. | Diagnostic/hold; không tự active FAQ hay thay production pointer. |
| M2 RAG | `eval_harness/rag_corpus.py`, `rag_runner.py`, `rag_review.py`, `run_m2_rag.py` | Catalog chunk BTC, PostgreSQL FTS/public-only producer, QA import cho answer/version. | 60 câu live/QA chưa hoàn tất; Q20/Q57 vẫn cần xử lý tranh chấp. |
| M2 khác | `eval_harness/simulation.py`, `reflection.py`, `suite_bundle.py`, `package.py` | Rule kernel simulator, Reflection draft, adapter evidence P8–P10, gói handoff/readiness. | Chưa có đủ customer-model 3 seeds, playbook active/R2, producer/evidence acceptance thật. |
| Product bridge | `product_adapter.py`, `prepare_product.py`, `product_smoke.py`, `run_product_full.py`, `web_tool_worker.py` | Chuẩn bị bundle/snapshot, IPC cô lập và BTC mock tools cho product run. | Snapshot cần dựng lại sau khi port code product; bundle cũ chỉ là evidence lịch sử. |

CLI chung là `run_eval.py` (`preflight`, `run`, `collect`, `score`, `report`, `benchmark`, `compare-rounds`, `release-gate`, `suite-bundle`, `package`). Theo yêu cầu bàn giao chỉ source, nhánh `dai` **không kèm bộ unit tests**; `check` cần bộ đó nên không dùng ở checkout này. Kết quả test offline trước đây không chứng minh model thật đạt điểm.

## Dữ liệu và kết quả đã tạo

- `normalize_output1.py` tạo `datasets/output1-btc-diagnostic-v1/` từ `output (1)/` với source hash và conversion report. Đây là 5 scenario/12 call JSON; GT do nhóm diễn giải, **chưa được QA duyệt**. Gói bàn giao chỉ giữ JSON nguồn, không kèm audio nguồn.
- `datasets/p5-current/` là bộ tạm/provisional. Nhánh `dai` không kèm `integration/`, `runs/`, ASR audio/model/virtualenv hay báo cáo chạy lịch sử; đây là source handoff, không phải evidence archive. Registry ASR cần audio được bổ sung sau mới chạy inference/replay.
- BTC ở `BTC-Data-Vong1-TEAMS/`, `evaluation-contracts/sources/btc/` và `output (1)/` là nguồn. Sửa GT phải tạo revision mới, ghi lý do/hash và xin QA duyệt.

## Phụ thuộc vào code product đã lưu

[Bản tham chiếu](product-integration-reference/README.md) chứa `backend/src/agents/{call_runtime,runtime_store,memory,orchestrator,policy,qa,evaluation_bridge,mcp_business,mcp_memory}.py`, API evaluation và setup PostgreSQL sandbox; không kèm tests. Đó **không phải** code active trong checkout product hiện tại. `mcp_business`/`mcp_memory` mới dùng FastMCP cùng process; chưa có MCP process isolation/writer hay LangGraph checkpointer. Đọc [trạng thái kiến trúc](architecture-status.md) trước khi chọn phần cần port.

## Kiểm tối thiểu, không gọi model

Cài dependencies từ `evaluation/evaluation-contracts/requirements.txt`, rồi chạy `python evaluation/evaluation-contracts/check_contracts.py` từ root repo để xác minh 46 hash BTC. Bộ unit tests đã bỏ theo yêu cầu và cần bổ sung lại khi tiếp tục phát triển. Không chạy product PostgreSQL bằng source chưa port rồi coi lỗi thiếu module là lỗi evaluator.

Không công bố M1/M2 PASS từ bộ diagnostic hoặc test offline. Cần GT/QA, product bridge tương thích, model run có ngân sách mới và benchmark đủ quy mô.
