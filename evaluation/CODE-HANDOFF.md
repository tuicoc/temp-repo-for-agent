# Bàn giao phần đã phát triển trong `evaluation/`

Cập nhật 10/10/2026. Nhánh `dai` có **hai cây code khác nhau**: product đang chạy trong `../backend/src/`, evaluator đã phát triển trong `evaluation/eval_harness/`. Code product ở [product-integration-reference](product-integration-reference/README.md) là **bridge cũ, chỉ tham khảo**, không phải nơi code tiếp hoặc bản cần port nguyên trạng.

## Mở repo rồi code ở đâu?

| Việc | Source active cần mở | Trạng thái |
|---|---|---|
| Prompt/model của từng agent | `../backend/src/agents/{advisor,memory,policy,qa,simulator}.py` | Source product hiện hành. Router là luật tại `../backend/src/components/orchestration/rules.py`, không có OrchestratorAgent riêng. |
| Một lượt và sau cuộc gọi | `../backend/src/pipeline/hot/{graph,nodes,state}.py`, `../backend/src/pipeline/cold/after_call.py` | Luồng product hiện hành; API dùng `../backend/src/api/harness.py`. |
| MCP, memory, guard, cải tiến | `../backend/src/mcp/`, `../backend/src/components/{memory,guardrails,improvement}/` | Source product hiện hành; đối chiếu `../docs/design.md`. |
| Chấm BTC và báo cáo | `eval_harness/`, `run_eval.py`, `evaluation-contracts/` | Code evaluator đã có; dữ liệu 5 scenario ở `datasets/output1-btc-diagnostic-v1/`. |
| Nối evaluator vào product mới | `../backend/src/pipeline/eval/runner.py` cùng `product_adapter.py` | **Chưa xong:** product runner hiện còn `NotImplementedError`; adapter evaluator cũ kỳ vọng bridge IPC cũ. Đây là điểm nối cần làm trước khi chạy full/baseline thật. |

Thứ tự đề xuất: (1) đọc `../docs/design.md` và API `../backend/src/api/harness.py`; (2) chốt contract giữa product runner mới với hooks của `eval_harness/runner.py`; (3) implement một đường chạy 5 scenario full/baseline qua cùng hot/cold path, state tách biệt; (4) cho collector/scorer chấm JSON và kiểm missing evidence; (5) mới mở M2 từng module. Không chép `product-integration-reference/` lên `../backend/src/`: base product đã thay đổi lớn và có sẵn agent/MCP khác.

## Đọc trước khi code

1. `../docs/design.md` là thiết kế product hiện hành; `evaluation-flow.md` là flow chấm. `temp-repo-for-agent/docs/flow.md` là bối cảnh lịch sử, không override thiết kế hiện hành.
2. `evaluation-contracts/schema-contract-matrix.md`, `report-schemas.md`, `harness-acceptance-tests.md`; BTC chuẩn được pin ở `evaluation-contracts/sources/btc/`.
3. Bảng code dưới đây, rồi `architecture-status.md` và `LIMITATIONS.md` để thấy phần còn thiếu. `evaluation-implementation-plan.md` chỉ dùng tra gate P0–P10.

## Code evaluator đang có

| Phần | File chính | Đã làm được | Giới hạn hiện tại |
|---|---|---|---|
| Contract/nguồn | `evaluation-contracts/check_contracts.py`, `eval_harness/contracts.py`, `assets.py` | Khóa hash nguồn BTC, kiểm schema/fixture và AssetRef; đọc đầu vào đã pin. | Không được sửa nguồn/lock để hợp kết quả. |
| P1 input | `eval_harness/preflight.py` | Kiểm manifest/scenario/controls trước khi chạy. | PASS preflight không phải chất lượng Agent PASS. |
| P2 runner | `eval_harness/runner.py`, `environment.py` | Fixed-turn full/baseline, tool sandbox BTC, raw run bất biến và barrier theo adapter contract. | Cần adapter tới product hiện hành; `../backend/src/pipeline/eval/runner.py` vẫn là stub. |
| P3 collector | `eval_harness/collector.py`, `extractor.py`, `model_extractor.py` | Validate raw/evidence, trích facts/trace, audit và xuất BTC wire cohort. | Model extractor chỉ chạy khi cấu hình/chấp thuận API; không bịa evidence thiếu. |
| P4 scorer | `eval_harness/scoring.py`, `judging.py` | Gọi scorer BTC nguyên bản, thêm hard checks và chọn rubric/judge evidence. | Không có QA human labels đủ cỡ hoặc producer Judge live thì chưa nghiệm thu. |
| P5 dataset/ASR | `eval_harness/datasets.py`, `asr_suite.py`, `asr/` | Inventory dataset provisional, replay/infer ASR riêng, coverage/ITN/entity và lock cấu hình. | Lượt 5 scenario JSON hiện tại **không chấm ASR**; full BTC audio/validator vẫn deferred. |
| P6 báo cáo | `eval_harness/benchmark.py`, `metrics.py`, `reporting.py`, `p6_evidence.py` | Một pipeline P2→P6, tính full/baseline, latency/cost khi có evidence, nhập billing/casebook đã đóng. | Usage/timing/review thiếu phải INCOMPLETE; fixture không chứng minh ngưỡng M1. |
| P7 cải tiến | `eval_harness/rounds.py`, `release.py`, `prepare_product_pair.py` | So R0/R1 với controls, hash/approval/consumption/release recommendation. | Diagnostic/hold; không tự active FAQ hay thay production pointer. |
| M2 RAG | `eval_harness/rag_corpus.py`, `rag_runner.py`, `rag_review.py`, `run_m2_rag.py` | Catalog chunk BTC, PostgreSQL FTS/public-only producer, QA import cho answer/version. | 60 câu live/QA chưa hoàn tất; Q20/Q57 vẫn cần xử lý tranh chấp. |
| M2 khác | `eval_harness/simulation.py`, `reflection.py`, `suite_bundle.py`, `package.py` | Rule kernel simulator, Reflection draft, adapter evidence P8–P10, gói handoff/readiness. | Chưa có đủ customer-model 3 seeds, playbook active/R2, producer/evidence acceptance thật. |
| Product bridge cũ | `product_adapter.py`, `prepare_product.py`, `product_smoke.py`, `run_product_full.py`, `web_tool_worker.py` | Chuẩn bị bundle/snapshot, IPC cô lập và BTC mock tools cho kiến trúc trước. | Chưa nối product mới; dùng contract và ý tưởng, không dùng nguyên trạng để công bố run thật. |

CLI chung là `run_eval.py` (`preflight`, `run`, `collect`, `score`, `report`, `benchmark`, `compare-rounds`, `release-gate`, `suite-bundle`, `package`). Theo yêu cầu bàn giao chỉ source, nhánh `dai` **không kèm bộ unit tests**; `check` cần bộ đó nên không dùng ở checkout này. Kết quả test offline trước đây không chứng minh model thật đạt điểm.

## Dữ liệu và kết quả đã tạo

- `normalize_output1.py` tạo `datasets/output1-btc-diagnostic-v1/` từ `output (1)/` với source hash và conversion report. Đây là 5 scenario/12 call JSON; GT do nhóm diễn giải, **chưa được QA duyệt**. Gói bàn giao chỉ giữ JSON nguồn, không kèm audio nguồn.
- `datasets/p5-current/` là bộ tạm/provisional. Nhánh `dai` không kèm `integration/`, `runs/`, ASR audio/model/virtualenv hay báo cáo chạy lịch sử; đây là source handoff, không phải evidence archive. Registry ASR cần audio được bổ sung sau mới chạy inference/replay.
- BTC ở `BTC-Data-Vong1-TEAMS/`, `evaluation-contracts/sources/btc/` và `output (1)/` là nguồn. Sửa GT phải tạo revision mới, ghi lý do/hash và xin QA duyệt.

## Phụ thuộc vào code product đã lưu

[Bản tham chiếu lịch sử](product-integration-reference/README.md) chứa bridge cũ để tránh mất quyết định/provenance, nhưng product hiện hành đã có agent, MCP và LangGraph riêng. Chỉ lấy một chi tiết từ đó sau khi so với `../backend/src/` và `../docs/design.md`; **không port cả bản tham chiếu**. Nó không kèm tests.

## Kiểm tối thiểu, không gọi model

Cài dependencies từ `evaluation/evaluation-contracts/requirements.txt`, rồi chạy `python evaluation/evaluation-contracts/check_contracts.py` từ root repo để xác minh 46 hash BTC. Bộ unit tests đã bỏ theo yêu cầu và cần bổ sung lại khi tiếp tục phát triển. Không chạy product PostgreSQL bằng source chưa port rồi coi lỗi thiếu module là lỗi evaluator.

Không công bố M1/M2 PASS từ bộ diagnostic hoặc test offline. Cần GT/QA, product bridge tương thích, model run có ngân sách mới và benchmark đủ quy mô.
