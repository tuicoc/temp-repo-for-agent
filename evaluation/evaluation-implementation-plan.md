# Implementation plan — Evaluation M1 → M2

## Trạng thái triển khai mới nhất — 09/10/2026

Kế hoạch G0–G4 đã được user duyệt. G0/G1 có code và integration PostgreSQL bằng model giả;
G2 có runtime guard/PII/router/tool limits với tests; G3 có evaluator shared `CallRuntime`
và web sandbox API/UI opt-in. Khi bật flag, `/api/conversations` cũng dùng runtime chung;
call gián đoạn sau restart có durable status và QA reconciliation an toàn, không tự resume
tool/model chưa biết kết quả. G4 có source-backed QA review/HMAC/hash invalidation, rule-based
outcome producer và cặp R0→R1 sandbox diagnostic với controls/consumption hash. Lệnh
`benchmark-rounds` đã nối hai round vào P2→P7 scorer, kiểm cùng cohort/controls/FAQ hash
và hard cap model attempts trước khi chạy; chưa có R0→R1 run thật sau parser fix,
approval bridge hoặc release. Hai run Google synthetic hoàn tất 4/4 call nhưng extractor
trả rỗng do signed text block; parser đã sửa, probe JSON đạt, cần full revision mới.
Thiếu live model regression, multi-worker và dataset chuẩn.
M1 functional chưa PASS; M1 acceptance dataset vẫn provisional. M2 module
tests chưa mở tới khi các blocker G3/G4 được khép. Chi tiết: [LIMITATIONS L27–L34](LIMITATIONS.md).

Scope hiện hành theo [README](README.md#1-quyết-định-hiện-hành--04102026). **Deferred theo user:** `validate_scenarios.py` và audio/segments BTC đầy đủ; làm sau, không xin/tích hợp hoặc viết script thay thế trong P0–P10 hiện tại. ASR/audio team, schema/ID/input/preflight tối thiểu vẫn làm. Báo deferred trước run qua scope sidecar có AssetRef trong manifest sources; không coi scope hiện tại PASS là đầy đủ yêu cầu BTC.

## 1. Phạm vi và quy tắc implementation

Implement evaluation trong `evaluation/`: chạy Agent qua adapter, thu evidence, validate, gọi scorer BTC, chấm bổ sung, xuất báo cáo và so các vòng cải tiến. Không implement business Agent, memory store, Knowledge Gap Loop, Exemplar Bank, Reflection hoặc voice runtime trong evaluator. Liệt kê capabilities thiếu và chặn nghiệm thu tương ứng.

Chuẩn hành vi: `evaluation-flow.md`, contracts và acceptance tests trong `evaluation-contracts/`. Tái sử dụng tài nguyên BTC trước khi viết mới. Không bắt buộc Inspect/Ragas/DeepEval/Langfuse hay dịch vụ bên ngoài.

Quyết định đã chốt:

- Tool-Call Accuracy theo flow: `100 × TP / (TP + FP + FN)`, matching một-một theo thứ tự. Invocation đúng tên/args vẫn có thể TP khi tool trả lỗi; execution success kiểm riêng. Sai args tạo FP và expected chưa được đáp ứng tạo FN. Optional allowed calls không tạo FN; extra không được phép tạo FP.
- Cost/call = tổng runtime cost của cohort, bao gồm cost của call lỗi, chia số call hoàn tất. Báo attempted/completed/failed riêng. Completed là lifecycle kết thúc và after-call barrier hoàn thành, không phải TSR PASS hoặc chốt đơn. Mẫu số 0 → undefined. Judge/simulator cost tách khỏi Agent runtime cost.
- Baseline chỉ tắt đọc memory hội thoại phiên trước trên mọi đường truy cập; vẫn giữ working context trong call và state nghiệp vụ xuyên call.
- Giữ nguyên scorer, schemas, GT và assets BTC. Metric/check nhóm nằm trong supplemental report, không ghi đè official report.
- Model/provider là cấu hình bắt buộc của deployment, không chọn lại theo điểm benchmark. Pin model/params/prompt/tool/KB/catalog/hardware giữa full và baseline. Pin judge/extractor/simulator riêng trong manifest.
- Agent/tool retry = 0, kể cả SDK. Judge format repair tối đa 1 lần, tổng 2 attempts. Timeout mặc định agent/tool/after-call/judge = 60/30/60/60 giây, cho phép cấu hình và ghim trước run; đây không phải ngưỡng latency nghiệm thu.
- Mỗi phần phải có positive/negative tests và evidence nghiệm thu trước khi chuyển phần. Không đánh dấu PASS từ việc đọc đặc tả.

## 2. Tài nguyên phải dùng lại

Inventory đã đối chiếu với `../BTC-Data-Vong1-TEAMS/` ngày 04/10/2026. Root là symlink tới Downloads; benchmark không đọc nguồn thay đổi âm thầm. Mặc định dùng bản pin ở `evaluation-contracts/sources/btc/`, kiểm `sources.lock.json` trước run. Gói root và bản pin chỉ khác nội dung rubric ở newline cuối file, không khác JSON semantics; không cập nhật lock chỉ vì whitespace. Khi nhận bản BTC thực sự mới, tạo snapshot/version/lock mới, giữ bản cũ và provenance.

| Tài nguyên hiện có | Dùng trực tiếp | Không tự xây lại / giới hạn cần xử lý |
|---|---|---|
| `eval/reference_eval.py` | RQR, CCR, TSR, TSR hard, HR, guardrails, memory heuristic, turns/call, Calls-to-Close, latency, ASR, RAG | Không viết scorer thay thế. Scorer chưa chứng minh tool execution/value/profile đúng, chưa kiểm coverage đầy đủ, chưa bỏ warm-up |
| `eval/mock_tools.py` | 9 business tools, quote/KM, inventory/date, CRM/identity, orders, callback, handoff; `--selftest` | Bọc module và cô lập state; không viết lại công thức KM/COD/ngày nghỉ. Không coi đây là memory implementation |
| `catalog/` | 40 parent products, 96 variants, 13 promotions, 50 CRM customers, 12 inventory events | Dùng làm môi trường/nguồn GT; không sinh catalog/CRM/KM mới cho eval. README nói 14 KM nhưng JSON có 13 |
| `policy/` | 14 tài liệu, 99 mã mục | Giữ chunk IDs, bảng, ngày hiệu lực, bản cũ, nội bộ và tài liệu nhiễu; không làm KB sạch bằng cách bỏ các bẫy |
| `schemas/` | Trace, Call Brief, Handoff Brief; tool descriptions và scenario format | JSON schemas có sẵn dùng nguyên bản. `tools.schema.json` là mô tả tool, không phải JSON Schema thực thi; dùng contracts nhóm để validate args |
| `test_set/public_sample/` | 7 scenario, 13 call, 39 lượt; 3 scenario có `hard_case` | Compatibility/dev suite, không phải Frozen hoàn chỉnh; SAMPLE-07 chỉ có 1 call. Không sửa nguồn để phù hợp Agent |
| `eval/runs/` | Full/baseline traces và report mẫu | Golden regression cho scorer/report. Là synthetic examples, không phải kết quả Agent hay latency thật |
| `eval/make_example_trace.py` | Tham khảo wire format và generator test fixtures nếu cần | Không dùng làm runner Agent: script tạo đáp án từ GT và latency ngẫu nhiên; không chạy ghi đè source `runs/` |
| `eval/llm_judge_rubric.json` | Prompt và J01–J12, agreement protocol | Chỉ implement selector/invocation/validation/human audit; không viết rubric mới |
| `simulator/` | 12 persona prompts, patience theo call, 8 quy tắc | Implement state machine và model invocation quanh spec, không tự tạo persona hoặc simulator rules mới |
| `rag/qa_labeled.json` | 60 câu có labels/expected answers, 6 loại | Không tự gán lại RAG gold set; retrieval dùng BTC scorer, answer/version dùng check riêng |
| `asr/ground_truth.json` | 4 mẫu D01–D04, 34 lượt, normalization/entity labels | Chưa có WAV/segments; không coi transcript là audio. 8 dialogue còn lại và audio đầy đủ chờ BTC |
| `evaluation/asr/` | Local ASR runner, ITN/entity processing, tests, model lock và datasets hiện có | Không dựng ASR pipeline thứ hai, không tải/chạy model mới chỉ để làm evaluator. Report lịch sử không thay benchmark mới |
| `evaluation-contracts/` | Schemas, 51 valid/18 invalid examples, 18 semantic mutations, checker, A01–A18 | Mở rộng phần còn thiếu, không tạo bộ contract song song |

`validate_scenarios.py` và script sinh audio được README BTC nhắc đến nhưng không có trong inventory. Validator BTC và audio/segments BTC đầy đủ **deferred**, không import/xin/tích hợp hoặc implement validator thay thế trong scope hiện tại. Chỉ làm schema/ID/input/asset/date checks tối thiểu; consistency checks nâng cao qua mock làm sau, không là gate P1 hiện tại. Không bỏ kiểm tool execution, source rights hay GT disputes.

## 3. Giao diện và artifacts cố định

### 3.1. Entry points

Tạo package `evaluation/eval_harness/`, config JSON và một wrapper `evaluation/run_eval.py`. Python ≥3.10; stdlib cho CLI/subprocess/hash/JSON, dùng `jsonschema` đã có. Unit tests evaluator dùng `unittest`; tái sử dụng ASR tests hiện có. Không thêm framework evaluation hoặc database cho evaluator.

Các lệnh mục tiêu chạy từ workspace root:

```sh
# Hiện đã implement P0–P4 offline/fixture; không phải benchmark Agent thật.
python -B -m evaluation.eval_harness check
python -B evaluation/run_eval.py check

# Chỉ kiểm input gate; fixture P1 chưa có adapter nên trả2, không chạy Agent.
python -B -m evaluation.eval_harness preflight --settings evaluation/p1-settings.example.json --for-execution

# Mục tiêu P2+P3, chưa implement: wrapper chạy một cấu hình và xuất trace BTC.
python evaluation/run_eval.py --scenarios <dir> --config full --out <full.jsonl> --settings <settings.json>
python evaluation/run_eval.py --scenarios <dir> --config baseline_no_memory --out <baseline.jsonl> --settings <settings.json>

# P2 hiện chỉ raw fixed-turn, trả2 do pipeline evaluation chưa hoàn tất:
python -m evaluation.eval_harness run --settings <settings.json> --scenarios <dir> --round R0 --out <new-run-dir>

# Fixture có sẵn (không cần --scenarios), mặc định cả hai config:
python -m evaluation.eval_harness run --settings evaluation/p2-settings.example.json --round R0 --out <new-fixture-run-dir>

python -m evaluation.eval_harness preflight --settings <settings.json> --scenarios <dir>
python -m evaluation.eval_harness score --run <run-dir> --out <new-report-revision-dir>
python -m evaluation.eval_harness compare --reference <R0-run-dir> --candidate <R1-run-dir> --out <new-comparison-dir>
python -m evaluation.eval_harness acceptance --level M1 --out <new-acceptance-dir>
python -m unittest discover -s evaluation/tests
```

README hiện cung cấp settings fixture P1, chưa có deployment default thật. Runtime cần settings tường minh với adapter được pin; chỉ cho bỏ `--settings` khi đã có bản default thật được pin sau này. Không fallback sang test adapter. API keys chỉ lấy từ environment, không lưu trong manifest/settings/adapter descriptor. Không ghi đè `--out` đã tồn tại. `score` chỉ replay evidence và tạo report revision mới, không chạy Agent và không tạo latency mới.

Exit code của lệnh benchmark/score/compare mục tiêu: 0 = mọi check áp dụng PASS+COMPLETE; 1 = confirmed FAIL, kể cả FAIL+INCOMPLETE; 2 = UNDETERMINED/INCOMPLETE; 3 = CLI/config không hợp lệ. `run` ở P2 hiện trả2 kể cả raw execution đủ vì raw chưa qua collector/scoring/suites; đọc runner-report để biết execution_complete. Wrapper chấm chéo sau P3 trả0 khi đã xuất đủ trace hợp lệ, không yêu cầu Agent đạt chất lượng; evidence thiếu trả2. Acceptance CLI trả theo kết quả test harness, không theo chất lượng câu trả lời của Agent bị fault injection.

### 3.2. Agent adapter

Chỉ dùng một contract adapter nhỏ để nối runtime thật và test adapter phục vụ integration/fault injection:

- `open_scenario(runtime_context)`: namespace, seed business state/history một lần, phiên bản cấu hình, event sink.
- `start_call(call_context)`: identity/channel, virtual date, memory-read policy; xuất Brief và before-call snapshot.
- `run_turn(customer_text)`: phản hồi Agent, events thực tế, backend timing/usage.
- `end_call()`: await after-call barrier, trả completion/outcome và after-call snapshot.
- `close_scenario()`: đóng tài nguyên đúng namespace, không đụng production state.

Runtime context không chứa oracle grading: không truyền `facts_established`, `must_not_ask`, `must_carry_over`, `success_if` hoặc `ground_truth_facts`. Seed history/CRM được phép là dữ liệu nghiệp vụ riêng, có provenance. `must_not_ask` trong Call Brief do runtime tự dựng từ memory, không copy từ scenario labels.

Capabilities khai báo trước run: business tools, memory isolation/read gate, after-call barrier, snapshots, briefs, timestamps, usage; M2 thêm retrieval, diarization, voice/VAD/concurrency. Thiếu capability → issue và không nghiệm thu suite liên quan. Không tự fallback sang test adapter. Tách runtime factory/model config khỏi HTTP chat/auth; không dùng session user thật để benchmark.

### 3.3. Run artifacts

Mỗi run có manifest, source/dataset locks, expected coverage, raw transcript/events, full/baseline JSONL, brief/memory/timing/extraction evidence, validation, official/supplemental reports, comparison/table, errors và release decision. ASR/RAG/judge/simulator/human evidence ở subfolders riêng. Dùng producer→consumer layout trong `schema-contract-matrix.md`, không định nghĩa layout cạnh tranh.

Raw append-only khi thu, đóng file rồi hash; reports tham chiếu path/hash/JSON Pointer, JSONL thêm context anchor. Không sửa raw khi schema lỗi; lưu invalid-object evidence riêng, không đẩy object sai vào scorer. Không giả zero tokens/timing khi provider không cung cấp. Verdict/completeness giữ hai trục, FAIL không mất khi thêm thiếu evidence.

## 4. Các phần implementation theo thứ tự

### P0 — Đồng bộ contract và bộ kiểm compatibility BTC

**Implement:**

- Kiểm đồng bộ contract docs v1.1.0: tool-accuracy.v2 theo flow, cost-call.v1 chia completed, A14 và tests. Không tăng version lại nếu chưa đổi ý nghĩa; không sửa nguồn BTC/run cũ.
- Dùng TimingEvidence1.1.0 nullable measurements, legacy1.0.0 còn được đọc với constraints cũ. Missing → null + Issue/INCOMPLETE; số0 chỉ khi đo được hoặc charge0 có nguồn.
- Khóa source inventory bằng checker hiện có. Tạo test chạy `evaluate` trên hai trace mẫu và đối chiếu toàn bộ system/baseline trong `report_example.json`.
- Chạy mock selftest trong subprocess riêng. Không chạy example trace generator để tạo báo cáo nghiệm thu.
- Bổ sung CLI shell tối thiểu và README lệnh tests; chưa gọi model.

**Đầu ra:** contracts thống nhất; source/compatibility tests offline.

**Gate:** checker vẫn đạt; full/baseline report parity exact; mock selftest thành công; tests TCA execution-error và cost completed=0 đạt. Chưa tuyên bố Agent PASS.

**Đã implement 04/10/2026:** package/CLI `check`, reuse checker, matcher context-level và cost arithmetic tối thiểu, 14 regression tests offline (gồm function parity và report BTC CLI nguyên JSON). Chạy lệnh ở README để tái kiểm. Matcher kiểm invocation độc lập outcome, không phải tool-success/state/coverage end-to-end. Không tăng schema version, không sửa source BTC/lock. P0 không tạo settings/model config giả; P1 bổ sung settings manifest/scope/preflight, P2 có explicit fixture adapter/raw runner. CLI check hiện chạy P0–P4; collect/export-trace/score offline đã có, compare/acceptance và wrapper BTC một lệnh chưa implement.

### P1 — Bọc mock environment và preflight

**Implement:**

- Dùng nguyên module BTC và `TOOLS`; bọc để log args/result/time/state và expose cho runtime adapter. Không viết lại business logic hoặc tạo MCP server mới trong evaluator.
- Mỗi scenario/config chạy trong worker process mới; trong worker, load module riêng, deep-copy seed data, giữ `_ORDERS`, `_CALLBACKS`, `_TICKETS`, `_ONCE_USED` xuyên call và không chia sẻ với worker khác. Runtime external phải chứng minh cùng isolation qua namespaces thật.
- Baseline filtering thực hiện ở runtime access layer, không sửa CRM/scorer BTC. Chặn CRM sessions/ledger/brief/precomputed summaries/cache có memory cũ, vẫn cho phép order business state.
- Inspect signature để chỉ inject `on` khi hàm nhận; log ngày của mọi ToolEvent. Không truyền `on` mù vào CRM/catalog/status/callback/handoff.
- Preflight schemas, IDs/call order/date overrides, noisy input length, assets trong cohort đăng ký, grading, applicability, split/source rights và quy mô. Ghi deferred trước run; asr_ids hiện chỉ audio team, không đổi expected IDs sau run để che thiếu.
- Scenario team vẫn dựa catalog/policy BTC và GT review độc lập; không lấy output Agent làm đáp án. Validator/consistency module nâng cao deferred, không phải gate P1 hiện tại.
- Giữ các bất nhất public GT vào dispute registry; không sửa SAMPLE-01 budget, SAMPLE-02 promo, SAMPLE-03 order ID hoặc Q20/Q57 để làm đẹp số.

**Đầu ra:** isolated BTC environment, config/manifest/coverage plan, dispute/capability report.

**Gate thành phần P1:** run full rồi baseline không rò orders/callback/tickets/promo usage; giữ state xuyên call trong worker; inventory thay theo date; CRM baseline lọc sessions cả ambiguous candidates nhưng giữ orders; inputs/refs/coverage/disputes được preflight kiểm. Selftest output không thay unit assertions cho wrapper. **Gate integration A11/A16 đầy đủ** cần runtime adapter/lifecycle P2 và collector P3; còn NOT_RUN, không tick PASS từ component tests.

**Đã implement 04/10/2026:** spawned mock worker + evaluator-only event/state audit, Assets resolver với root được khai báo, strict JSON, preflight dùng manifest/scope pin; settings example và scope fixture có nguồn/quyền synthetic được đánh dấu rõ. 14 component tests P1 +4tests chuẩn bị P2; thêm10tests P2, CLI `check` hiện chạy chung68tests sau P4 (55 ở mốc P3,42 ở mốc P2). P1 không dựng Agent/ledger/cache/brief runtime; preflight không bind nên capability report giữ NOT_RUN/NOT_BOUND. Scope hiện tại và tham chiếu schema không đổi; BTC46file/source lock giữ nguyên. Quyền source/PII là records khai báo cần review thật, chưa kiểm authority. P2 lưu raw/partial execution và hash file đóng; P3 chuẩn hóa/validate evidence/provenance. Xem README để chạy và đưa dataset mới vào.

### P2 — Fixed-turn runner và wrapper chấm chéo

**Implement:**

- Dùng execution gate riêng: chỉ development dispute không chặn thử bind; vẫn giữ OPEN/INCOMPLETE. Regression/official dispute và mọi issue khác đều chặn, không drop cohort hay ignore errors.
- Settings nhận optional `adapter` AssetRef; descriptor/code đều pin trong manifest.sources. Bind đúng code/entrypoint và kiểm hooks/capabilities thực trước lượt đầu; khai báo đủ chưa chứng minh runtime đủ.
- Nối lifecycle adapter; test adapter chỉ dùng kiểm harness, không trả đáp án từ GT trong benchmark.
- Chạy calls theo thứ tự số, ngày mặc định 2026-10-15 timezone Asia/Ho_Chi_Minh, `days_later` cộng dồn và `call_date` override.
- Feed `customer_turns_asr` nếu có, không thay bằng clean text. Fixed-turn chạy đủ kế hoạch, kể cả >12 lượt. Không dùng responder phản ứng theo Agent ở M1.
- Seed một lần, await after-call thực trước call sau. Timeout barrier ghi infra/missing và không chạy tiếp như memory đã sẵn sàng.
- Side effect timeout cần reconciliation evidence; không tự retry. Ghi partial evidence khi hạ tầng lỗi.
- Wrapper nhận scenario directory mới của BTC, không hard-code 7 public IDs hay số lượt. Fixture mode gắn nhãn và nằm ngoài acceptance quality report.

**Đầu ra P2:** raw/partial execution từ test adapter và runtime adapter, CLI full/baseline. Wrapper xuất trace BTC đầy đủ là đầu ra chung P2+P3; không tạo questions/claims rỗng hoặc latency0 để thay evidence chưa thu/extract.

**Gate:** component P2 kiểm lifecycle, 13 lượt fixed-turn chạy đủ, baseline working context vẫn dùng được và call2 đợi memory barrier. A01/A04/A11/A12-fixed/A16 end-to-end và wrapper trace cần P2+P3. Chạy smoke trên public samples với Agent thật khi hooks/capabilities đủ; không yêu cầu sample TSR 100% để nghiệm thu runner, không suy chất lượng Agent từ test adapter.

**Đã implement phần runner P2 04/10/2026:** [runner.py](eval_harness/runner.py), CLI `run` hai nhánh hoặc `--config`, snapshot input pins, adapter process nạp đúng code bytes + signature/capability/retry declaration checks, BTC tool RPC chỉ trả filtered results, seed_history có provenance một lần, awaited sync/async lifecycle, fixed-turn/noisy input/date override, barrier/timeout/no retry và raw/partial append-only + closed-file hashes.10fixture/fault tests nâng tổng42, gồm lost reply sau tool commit, baseline working context và isolation business state. Settings/descriptor/code fixture có pin riêng, không fallback. Xem protocol/lệnh/layout tại README.

**Chưa nghiệm thu:** product adapter/DB/cache/KB/SDK retry thực và smoke Agent thật; live capability declarations không chứng minh các hành vi này. `execution_complete` chỉ raw runner, evaluation còn INCOMPLETE. Export wire offline đã có P3; wrapper BTC một lệnh và A01/A04/A11/A12/A16 end-to-end còn chờ runtime integration; không tạo prediction/timing giả hoặc tuyên bố fixture đạt đề. P3 cần tái sử dụng raw P2 thay vì chạy Agent lại chỉ để chuẩn hóa artifacts.

### P3 — Collector, evidence validation và extractors

**Implement:**

- Thu transcript có speaker/role, tool results/state effects, briefs tại đúng thời điểm, memory before/after, backend clocks và usage per operation/call.
- Schema + semantic checks: coverage, duplicate, path/hash/pointer, quote theo Unicode code points, role/content, temporal order và customer/profile.
- Extract open/confirm questions, atomic claims và facts used từ actual Agent texts/tool args; không dựa GT để tạo prediction. Preserve value sai, không sửa về gold.
- Exclude consultant/tool text khỏi Agent claims. Fact xuất hiện trong memory không tự thành fact được dùng. Unknown mapping/extractor error phải báo thiếu.
- Pin extractor prompt/model/schema; cache theo hash input+versions để replay. Ghi raw extraction output/validation; không retry để chọn nhãn đẹp.
- Export audit ngẫu nhiên 20 lượt, người chấm nhập JSON; kiểm lỗi bỏ sót/role/value. Không tạo nhãn người bằng model.
- Map extraction/events sang trace schema BTC, sidecars giữ evidence nhóm. Thu `memory_writes` khi scenario có expectation.

**Đầu ra:** valid BTC traces, evidence sidecars, validation/coverage và extractor audit.

**Gate:** A02/A03/A05/A06; confirm lặp, 2 claims một câu, wrong profile, wrong value, brief invalid vs missing đều có tests. S01–S24 áp dụng được phải kiểm trên run evidence, không chỉ fixture.

**Đã implement offline 04/10/2026:** immutable P2 replay/snapshot, typed evidence, strict hash/pointer/Unicode/role/profile checks, coverage không co mẫu, fixture extractor descriptor/records/schema/code pins và cache, BTC mapping/export đủ wire, audit sample theo seed.13 test P3 gồm confirm lặp/2 claims/wrong value/profile/brief invalid-missing/timing/role/hash/partial export/memory writes. README có protocol và lệnh. Không gọi Agent/model, không sửa DB/RAG/source BTC. Old echo P2 thiếu typed memory/predictions giữ INCOMPLETE.

**Còn pending trước nghiệm thu P3 đầy đủ:** extractor model/prompt thật, usage runtime, independent human review/import gate20turn, S01–S24 và A02/A03/A05/A06 trên runtime evidence. `export-trace` hiện là bước riêng sau `run`/`collect`, chưa phải wrapper BTC một lệnh. Không tick P3/acceptance hoàn chỉnh từ fixture xanh; P4 score đã replay sang revision riêng; collector report cũ giữ nguyên pending tại thời điểm thu.

### P4 — Scorer wrapper và supplemental grading

**Implement:**

- Chạy BTC CLI nguyên bản trong subprocess để xuất official report; lưu argv/source hash/stdout/stderr. Dùng functions cùng nguồn BTC cho unit tests/standalone ASR-RAG, không copy công thức.
- Nếu trace thiếu/sai, giữ partial evidence; scorer chỉ chạy trên valid input nếu có ích chẩn đoán. Report chẩn đoán không được vượt coverage gate.
- Bổ sung tool execution/state verification, fact value/context, memory supersede/TTL/profile, handoff schema/content, PII và GT coverage.
- TSR/CCR/HR/Calls-to-Close official giữ nguyên. Báo verified-order close bổ sung vì BTC đếm invocation, không chứng minh đơn thành công.
- Ghi assertion-only/judge-only/hybrid theo grading contract; tại M1 chỉ đăng ký phần áp dụng, judge M2 chưa chạy không biến thành PASS.
- Evidence error phân loại schema_error/missing_evidence/agent_violation/dispute/infra_error; confirmed FAIL + missing giữ FAIL+INCOMPLETE.

**Đầu ra:** official-report.json và supplemental-report.json có evidence/cohort/formula refs.

**Gate:** P0 parity còn xanh; A01/A03/A05/A18; BTC TSR có thể PASS khi tool business_error nhưng supplemental phải FAIL. Negative-only scenario thiếu trace không được tổng kết PASS.

**Đã implement offline 04/10/2026:** CLI score và scoring.py snapshot/replay closed P3 evidence, BTC subprocess nguyên bản + argv/hash/stdout/stderr, schema report và coverage gate độc lập. Supplemental kiểm invocation/outcome/state (mock BTC), fact/claim GT/profile/memory integrity/brief/guardrail và assertion routing, giữ FAIL+INCOMPLETE.13 tests P4 kiểm exact CLI parity, negative-only missing/duplicate/schema, invocationTP+business-error, verified new order vs seed/no state, TTL/delete, hybrid pending, schema fragments, role/config leak, CLI/hash/no-overwrite và scorer failure. Không sửa BTC/source lock/raw run cũ, không thêm framework/database.

**Pending nghiệm thu:** runtime DB/state verifiers, GT/expected-tool labels và PII policy chốt trước run; audit/model extractor/usage còn thiếu theo P3. Memory expectation shape chưa rõ (address_ttl_check/profile_state) và handoff prose review giữ INCOMPLETE, không suy semantics từ chuỗi. Judge P8, metrics/cost/latency benchmark P6, dataset P5 và RAG P9 chưa implement trong P4. Gate A01/A03/A05/A18 end-to-end còn NOT_RUN, không tick PASS từ fixtures.

### P5 — Dataset team và tích hợp ASR hiện có

**Override triển khai hiện tại theo user 04/10/2026:** dùng dataset đã có, bộ đúng bổ sung sau; không cần chờ human review để implement/chạy bộ tạm. Registry phải `provisional=true`, pin waiver `USER_SKIP_REVIEW_TEMPORARY_DATASET_2026_10_04`; review status thật giữ nguyên. Các mục Frozen/review/quota dưới đây vẫn là đích nghiệm thu, không phải lý do tự sinh thêm dữ liệu hoặc chặn bộ tạm. Không miễn review/audit/authority của các phase khác.

**Implement:**

- Giữ public samples là compatibility suite riêng. Tạo Frozen M1 của team 20 đa phiên thông thường +5 ca khó riêng, mỗi scenario 2–3 call; tất cả dựa catalog/policy/mock BTC. M2 mở rộng thành ít nhất 40 trước khi đo M2.
- Giá/KM/variant và thời gian từ BTC, identity dùng CRM seed phù hợp; bổ sung dialogue/expectations của team, không sinh catalog mới. Order ID generated khác gold cần thiết kế seed/business fixture công khai trước run, không ép mock sinh ID từ đáp án ẩn.
- Frozen/Growth/dev tách version và customer IDs; case biến thể/replay không tính như lỗi hay evidence độc lập. Growth không nhập vào mẫu số Frozen.
- Inventory dataset sản phẩm C.1 báo riêng với quy mô evaluation C.4; 25 scenario không tự chứng minh 120 transcript/40 audio/1 giờ/30 khách đa phiên/10 khách đa kênh. Kiểm các quota theo đề, không tự gộp parent SKU và variants để tuyên bố đủ M2.
- Gọi `evaluation/asr/run_eval.py` và text processing/tests hiện có qua thin suite adapter; không tạo ASR runner mới. Chọn model local đã có qua config lock; historical runs chỉ là regression inputs, không là kết quả run mới.
- Dùng ≥20 audio eval team có GT/review; kiểm hash audio/GT/model/preprocessing và raw→normalized→ITN lineage. Tái sử dụng datasets đã có khi phù hợp, không sinh TTS có phí tự động.
- Audio/segments BTC đầy đủ deferred: không xin/tải/sinh/tích hợp tại P5; giữ D01–D04 làm format reference, không tổng hợp thành BTC measurement. Mở lại sau bằng scope/version/run mới; không synthesize lại rồi gọi là BTC audio.
- Giữ riêng raw WER/CER và numeric-normalized view; phone/money exact-match sau ITN, không pad/fix digits. ASR time/phút không nhập vào TTFT.

**Đầu ra:** reviewed Frozen dataset/locks, dataset readiness report, ASR suite evidence/coverage/report.

**Gate:** A09/A16 trên audio team/fixtures; missing trong cohort đăng ký không im lặng skip. BTC audio deferred không chặn implementation hiện tại nhưng report ghi chưa nghiệm thu audio BTC đầy đủ. Human review team vẫn cần khi nghiệm thu bộ đúng; riêng bộ tạm áp dụng waiver user ở trên, không biến unreviewed thành verified. Không đặt ASR PASS threshold BTC chưa có. Readiness toàn bộ đề khác completion scope hiện tại.

**Đã implement scope bộ tạm:** `dataset-readiness` ghim registry/version/hash và kiểm inventory/quota/split/audio/lineage; `asr-suite` gọi runner ASR hiện có, snapshot inputs, native evidence/logs, typed Coverage/ValidationReport và closed-file lock. Default replay Medium dev4/eval20 không đo inference/timing mới; mode infer explicit pin local model/dev lock. Thiếu Frozen/C.1 hoặc provisional không chặn execution bộ tạm, các lỗi integrity/coverage/review-required vẫn chặn hoặc INCOMPLETE.16 tests P5, chưa chạy model mới; fixtures không được tính quota Frozen. Thay bộ đúng bằng registry/settings/run mới, không sửa lịch sử. P6 mới aggregate metrics/table; chưa tick M1/A09/A16 end-to-end hay full benchmark từ replay. Xem README P5/lệnh/report.

### P6 — Metrics, bảng A.6 và mốc M1 một lệnh

**Đã implement/chạy offline ngày 04/10/2026:** CLI `report` từ closed P4/P5 và `benchmark` một lệnh ghép P2→P3→P4→P5→P6. Dùng BTC functions nguyên bản, raw ratios cho gates, typed Metric/Comparison/SupplementalReport/ValidationReport, table/errors/casebook triage và immutable lock. Fixture full/base2turn/config + ASR eval20/20 replay chạy xuyên suốt, không lỗi pipeline; FAIL+INCOMPLETE dự kiến, không M1 acceptance. P6 có10 tests riêng; README mô tả commands/receipts và chấm chéo.

**Bổ sung07/10:** closed billing ledger/casebook review importers đã có (`report --usage-run/--casebook-run`), kiểm exact raw hooks/binding/receipts/price/currency và retest run thật khác source, không qualify fixture. RQR exact40% float boundary đã fix bằng Fraction. Protocol ở [P6 evidence](p6-input-evidence.md). Pending nghiệm thu: ≥100 effective timings/config, producer usage/pricing/runtime/DB/audit/labels và casebook10lỗi real; timing-repeat cohorts vẫn chưa implement, chỉ cần nếu chọn repeat protocol. Các phase tiếp theo **phải đọc/cập nhật [LIMITATIONS.md](LIMITATIONS.md)**; P7 partial bên dưới, P8–P10 chưa implement. Applicable suites chưa hỗ trợ giữ INCOMPLETE.

**Implement:**

- Benchmark `run` chạy full/baseline, các suite áp dụng, validation→BTC→supplemental→comparison và in bảng. Không chờ dựng dashboard.
- Table render chỉ từ report/comparison, không nhập tay. Báo RQR/CCR/TSR/TSR hard/HR price-promo, turns/call và turns/scenario riêng, guardrails, memory/handoff, ASR, raw/derived latency, cost và coverage.
- RQR relative reduction `(base-full)/base×100`; base=0 → undefined, không PASS giảm40. Supplemental gate tính từ tử/mẫu chưa làm tròn; official BTC flags giữ nguyên kể cả khác sát ngưỡng.
- TTFT backend token đầu, không dùng filler. Không streaming thì TTFT=Total theo BTC; không giả timestamp trung gian.
- Default thu ≥103 raw turns/config để còn ≥100 latency samples sau bỏ3 warm-up. Nếu bổ sung timing repeats, dùng run/repeat IDs riêng, không nhân mẫu số quality. Warm-up vẫn chấm chất lượng.
- Brief timing từ identity đến ready, gồm refresh KM/stock/new channels; báo max, không chỉ p95. BTC raw latency giữ nguyên, derived report dùng cùng p95 function BTC và loại warm-up IDs công khai.
- Usage/price/currency pinned; không cộng USD+VND nếu chưa pin tỷ giá. API charge0 khác compute chưa ước tính. Thiếu usage/price → incomplete, không fabricated0.
- Casebook ≥10 lỗi thật, có root cause/remediation/retest refs; thiếu quota báo thiếu, không nhân bản examples. Errors không tự thành Growth.

**Đầu ra:** run M1 đầy đủ, table.md, errors/casebook, README chấm chéo và benchmark.

**Gate:** A10/A14/A18; formula zero/missing/cohort/rounding tests; RQR giảm≥40%, TSR≥70%, HR giá/KM≤5%; M1 TTFT p95≤3s, Total p95≤8s, Brief max≤5s. Undefined mandatory metric/coverage thiếu không thành overall PASS; suite M2 N/A không chặn M1.

### P7 — So R0/R1 và kiểm candidate/release

**Cập nhật09/10:** release-gate typed ReleaseDecision recommendation cócode/negative tests, HMACauthority/pinnedpolicy/contentbytes/consumptioncoverage/control/cost/rawthresholds/casebookR0→specificR1 checks. Không productionmutation; reviewservice/UI/auth/versionactivation chưa implement. M2suite release/R2integration chưa đủ nênhold. KhôngđánhdấuA13/A15realPASS.

**Partial07/10:** `compare-rounds` đã có diagnostic typed Comparison, cohort/config/cost-policy checks, raw no-regression và staging readiness hold; thiếu R1 không dựng comparison giả. Candidate/approval/source-authority/runtime-consumption và typed ReleaseDecision **chưa implement đầy đủ**. L13 cần nhóm sản phẩm/user chốt nguồn artifact và cách xác minh quyền reviewer; không dùng string reviewer hoặc cờ self-declared để auto-active. Chưa qua gate P7/A13/A15, không báo phase hoàn tất.

**Implement:**

- Nhận candidate/version/approval từ sản phẩm, chạy cùng Frozen R0/R1. Dữ liệu public đã nhìn để sửa phải khai báo regression/test-seen; hidden chỉ report-only, không auto-learn.
- Compare pin dataset/hardware/model/tool/input và allowed changed improvement versions. Full/baseline trong mỗi vòng chỉ khác memory-read policy.
- Source Gate kiểm quyền/PII/provenance; approval đúng content hash và reviewer; candidate bytes đã duyệt phải đúng bytes đã đo. Không dùng nonempty string equality thay kiểm hash thực.
- Gate nhóm ghim trước run: RQR không tăng, TSR không giảm, HR price/promo không tăng; phải đạt ngưỡng bắt buộc và hard supplemental checks. Undefined/missing/dispute ảnh hưởng → hold.
- Xuất ReleaseDecision active/hold/rollback; evaluation không tự mutate con trỏ active production. R0 chưa có previous version thì hold thay rollback giả.

**Đầu ra:** comparison R0/R1, release decision và harmful-regression evidence.

**Gate:** A13/A15; sửa candidate1byte vô hiệu approval/evaluation; chưa có R1 runtime thực không tạo R1 bằng regrade trace R0. Đây là mốc hoàn tất measurement M1 và vòng cải tiến M1 khi đủ dependencies.

### P8 — Judge và human agreement M2

**Partial09/10:** BTCselector/prompts, max2rawattempts/quote/turncoverage/hybridAND/randomsample20/agreement+kappa vàsuite-bundle import cócode. Scheduler `produce_judge` đã giới hạn một repair, không retry provider error; chưa bind vào provider/closed trace hoặc human-label authority/P4 integration, chưa có actual provider/human agreement. Không gọi P8 full implemented chỉ từ component tests.

**Implement:**

- Dùng nguyên prompt/rubric J01–J12. Implement selector theo applies_to và trace, ghi lý do; ca yêu cầu handoff không được né kiểm chỉ vì Agent không gọi tool.
- Judge input có scenario/GT/transcript đúng role nhưng Agent không nhìn thấy; transcript là dữ liệu, không là instruction. Validate criterion IDs/verdict/evidence quote.
- Lưu hai raw attempts khi format repair; lỗi lần2 → verdict=null, UNDETERMINED+INCOMPLETE. Hybrid AND, hard FAIL không bị judge PASS đảo ngược.
- Export ≥20 random call×criterion pairs để người chấm độc lập; import labels, tính agreement/kappa và undefined cases. Kappa<0,6 phải phân tích, không âm thầm bỏ samples.

**Đầu ra:** judge records, human labels/agreement, audit errors.

**Gate:** A07/A18; wrong evidence/unknown criterion/JSON lỗi/missing applicable criteria/hardFAIL đều kiểm được. Human thiếu không gọi M2 complete.

### P9 — RAG, diarization và simulator M2

**Partial09/10:** RAGcanonical60qid/BTCscorer, midpointdiarization/segmentcoverage, simrulekernel/outline/state/seedsmetrics cócode. LiveRAGretrieval/answergrader, diarizationinference vàfullsimulatorAgentorchestration/classifications/expiryexplanation vẫn pending. Suiteimports runtimepending, fixed/SIM khôngmerge.

**Implement:**

- RAG chạy runtime retrieval trên nguyên 14 policy docs/99 chunks và 60 BTC questions; giữ section IDs, split `#fragment` mapping, version/access metadata. Không dùng expected_answer làm Agent input.
- Dùng `rag_eval` BTC: Recall@3/@5, multi-hop full recall, abstain/false-abstain và by-type. Validate đủ60qid trước score, vì scorer có thể skip missing. Answer/version chấm riêng bằng expected_answer + nguồn, không dùng J01–J12 thay rubric RAG chuyên biệt.
- Q20/Q57 và các tranh chấp giữ raw gold, retrieval vẫn đo; answer gate disputed giữ hold, không loại qid khỏi coverage.
- Diarization hiện nối inference trên audio/segments team và dùng BTC midpoint speaker accuracy, không gọi DER. BTC audio/segments đầy đủ deferred; không chờ chúng để implement/test harness. Không lấy TTS generation timing làm prediction.
- Simulator dùng 12 persona prompts/patience và state machine 8 rules theo đúng thứ tự; default temperature0.3 nếu provider hỗ trợ, seeds0/1/2 và cùng config giữa full/baseline. Lưu provider seed support/limitations, không cam kết determinism không có.
- Oracle chỉ simulator/scorer; Agent chỉ thấy lời khách. Fixed-turn và simulator artifacts/cohorts riêng. Cap12 customer turns/call chỉ simulator; infra timeout không giả customer refusal.
- Mean/std_population/range TSR theo seed; range≤10 điểm phần trăm là gate nhóm bảo thủ, ghi rõ BTC chưa chốt range hay std. Bộ5scenario lặp ba seed ghim trước run, không chọn ca sau khi thấy điểm.

**Đầu ra:** RAG, diarization và simulator reports/evidence riêng.

**Gate:** A08/A09/A12/A17; missing qid/seed/segments, confirm lần2, patience call3, unknown facts, silence2/3 đều có tests; không leak oracle, không merge simulator TSR vào fixed-turn report.

### P10 — Tool Accuracy, voice/concurrency, R2 và đóng gói

**Partial09/10:** TCAmatcherreuse/labelcoverage, voiceclock/uniqueplannedturns/duplicates/overlap/warmupquota vàimmutablepackage/A01–A18coverage/R0R1R2presence cócode. Liveplayback/VAD/concurrency/isolation, realR2/ablation, per-caseacceptanceverifiers vàfreshenvironmentportability vẫn chưa đủ. Package INCOMPLETE expected; khôngcertificationgiả. Usergoalarchitecturehoànthiệnchưaachieved.

**Implement:**

- Expected tool calls/name/args/conditions/order gán trước trong grading sidecar, không suy từ actual calls hoặc chỉ từ success_if. Tính TP/FP/FN, precision/recall theo quyết định đầu tài liệu; no scored call → undefined và no-tool correctness check riêng.
- Dùng tool result/state cho execution metric riêng. Calls-to-Close supplemental chỉ tính order mới được verified successful, không tính CRM seed order hay invocation lỗi.
- Voice suite lấy VAD-end→first played audio byte, Brief≤3s, hai session thật overlap; báo coverage/overlap intervals/isolation. Thiếu voice runtime không dùng clock giả hoặc đổi applicable=false sau run.
- R2 dùng runtime improvement artifacts thật; so R0/R1/R2 cùng Frozen, harmful changes và controlled ablation. M2 cần ít nhất2 cơ chế cải tiến sản phẩm, evaluator chỉ kiểm versions/evidence của chúng.
- Nếu sản phẩm dùng Exemplar/Reflection/A/B, bổ sung schemas và tests theo tài liệu tương ứng trước khi nhận artifact; không dựng cả4 cơ chế chỉ để hoàn tất evaluator. A/B là offline paired experiment riêng, không trộn với full/baseline và không auto-publish winner.
- Đóng gói dependency versions, default config, README commands, input/response examples, acceptance evidence và report references. Langfuse optional, không là dependency chạy offline checks.

**Đầu ra:** M2 suite bundle, comparison R0/R1/R2 và handoff package.

**Gate:** A10/A14/A18; Tool Accuracy tool-error vẫn TP invocation nhưng executionFAIL; voice TTFA p95≤2,5s và Brief max≤3s, ≥2 overlapping sessions; toàn bộ A01–A18 có machine-readable evidence. Fresh environment chạy hướng dẫn không phụ thuộc absolute paths máy dev.

## 5. Dependencies ngoài evaluation — checklist gửi nhóm Agent

| Capability còn thiếu/ cần xác minh trong sản phẩm | Contract bàn giao tối thiểu | Chặn mốc |
|---|---|---|
| Business tools của Advisor hiện còn rỗng | Bind tools từ isolated BTC environment, args/result/event capture; không cần viết lại mock | M1 E2E |
| Runtime call/session lifecycle | Adapter start/turn/end, scoped resources và virtual date | M1 E2E |
| Identity + profile/episodic memory | Đọc/ghi đúng customer, sources, supersede/TTL/snapshots; không copy facts_established oracle | M1 continuity |
| Baseline memory-read gate | Chặn ledger/CRM sessions/brief/cache/KB memory cũ; working context và order state vẫn dùng | Full/baseline comparison |
| After-call barrier | Completion thực hoặc timeout có evidence, không sleep giả | Call2+ |
| Call/Handoff Brief | Schema BTC, object thực ở đúng thời điểm, current working context khi handoff | Brief/handoff checks |
| Backend timing/usage | Actual token timestamps hoặc truthful nonstream timing; usage theo turn/call, không chỉ tổng process | Latency/cost |
| Improvement candidates/approval/consumption | Version/hash, nguồn feedback, người duyệt; runtime dùng R1/R2 thật | R0/R1/R2 |
| RAG retrieval/answer | Chunk IDs/version/metadata và answer, không feed gold answers | M2 RAG |
| Diarization/voice | Predictions/speaker segments, VAD/audio byte events, hai phiên overlap | M2 diarization/voice |

ASR/audio dependency nghiệm thu: audio/GT/segments team và human review; P5 được dùng bộ tạm/waiver user theo README mục1, bộ đúng bổ sung sau. BTC audio đầy đủ/validator deferred, không là blocker P0–P10 theo scope hiện tại. Giữ deferred list để mở lại sau, không tuyên bố hoàn tất mọi yêu cầu đề. Chỉ dùng tài nguyên có quyền, không gọi TTS trả phí/tải model mới tự động.

Dataset sản phẩm C.1 do nhóm dữ liệu bàn giao; evaluator kiểm inventory/quota/provenance, không tự xây toàn bộ training/development dataset. Model credentials/pricing và người chấm human audit là dependency vận hành.

## 6. Definition of Done

- [ ] P0–P4: compatibility/scorer parity và runner/evidence/scoring integration offline đạt; source BTC không bị sửa.
- [ ] Wrapper chạy directory scenario bất kỳ đúng format BTC, xuất trace full/baseline; README có lệnh chấm chéo.
- [ ] M1 scope hiện tại: runtime thật, Frozen đủ quy mô, full/baseline, ASR team, timing/cost, extractor audit, casebook và R0/R1 thật; BTC audio/validator deferred hiển thị rõ.
- [ ] M2: ≥40scenario, judge/human, RAG60, diarization, SIM3seeds, TCA, voice/concurrency, R2 và harmful-improvement analysis.
- [ ] A01–A18 được chạy và lưu evidence; các fault-injection tests chứng minh harness phát hiện đúng lỗi, không đòi Agent bị inject đạt chất lượng.
- [ ] Mọi metric có formula/unit/cohort/numerator/denominator/evidence; zero/missing/rounding kiểm được; GT disputes công khai.
- [ ] Chỉ suite áp dụng đủ evidence mới COMPLETE; confirmed Agent violations giữ FAIL; external assets chưa có ghi INCOMPLETE, không gọi Agent FAIL vì BTC chưa phát audio.
- [ ] Một lệnh benchmark in bảng có thể tái lập; score/replay không chạy Agent lại hoặc tạo measurement mới; report revisions/raw không overwrite.
- [ ] Phân biệt harness đã nghiệm thu, scope hiện tại complete, Agent đạt ngưỡng hay không và readiness toàn bộ đề. Deferred không gọi PASS/N/A của BTC; chỉ khi mở lại/đo đủ BTC audio mới tuyên bố nghiệm thu đầy đủ yêu cầu liên quan.
