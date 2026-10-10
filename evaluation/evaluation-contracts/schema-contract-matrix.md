# Contract triển khai Evaluation Harness — v1.1.0

Đọc [README — quyết định hiện hành](../README.md#1-quyết-định-hiện-hành--04102026) trước. Tool Accuracy dùng tool-accuracy.v2 theo invocation TP/(TP+FP+FN), cost/call chia completed. TimingEvidence mới có version1.1.0 nullable measurements, legacy1.0.0 vẫn giữ kiểu cũ; các artifact/grading khác còn1.0.0. Không đổi wire/source BTC. Validator và audio/segments BTC đầy đủ deferred theo user, không chặn scope team hiện tại; báo rõ chưa nghiệm thu toàn bộ BTC audio.

Đọc cùng [flow](../evaluation-flow.md). M1 trước, M2 sau. Đây là **đặc tả + fixture minh họa**; P2 raw runner đã có và được kiểm fixture/fault, chưa có extractor/judge/benchmark Agent thật hoặc full evaluation pipeline. Theo Ponytail, dùng lại schema BTC; một thư viện JSON Schema, một lệnh kiểm tra; không dựng framework mới.

## 1. Cài và kiểm tra

Tại thư mục `evaluation-contracts/`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python check_contracts.py
```

Cài dependency cần mạng hoặc wheelhouse có sẵn; lệnh kiểm tra sau đó chạy **offline**, không gọi model/tool/scorer. Python ≥3.10. Muốn cài hoàn toàn offline: mang wheelhouse phù hợp hệ điều hành/Python và dùng `pip install --no-index --find-links /path/to/wheelhouse -r requirements.txt`. Không coi dependency đã được đóng gói trong folder.

Hai schema nhóm: [contracts](contracts.schema.json) và [grading contract](grading-contract.schema.json). Validate bằng định nghĩa cụ thể, ví dụ `contracts.schema.json#/$defs/Manifest`; root contracts cố ý từ chối instance để tránh validate nhầm cả bộ. JSONL validate **từng dòng**, không validate nguyên chuỗi. Draft2020-12; contract bundle/docs1.1.0, TimingEvidence1.1.0 hỗ trợ null và đọc legacy1.0.0 theo constraints cũ; artifact khác/grading1.0.0. Đổi ý nghĩa phải version và giữ compatibility/migration, không sửa run cũ.

[examples.json](examples.json) chứa ví dụ cấu trúc cho mọi định nghĩa và mutation tạo ví dụ không hợp lệ. Các ví dụ độc lập chỉ chứng minh cấu trúc; reference mẫu dùng để minh họa hình dạng, không chứng minh đúng loại nội dung hay chất lượng. [fixtures](fixtures/) là chuỗi M1 giả lập full/baseline hai call, kèm Call Brief, handoff và grading contract. Không dùng các số này làm báo cáo Agent. [check_contracts.py](check_contracts.py) nêu rõ phạm vi thực kiểm; [nghiệm thu](harness-acceptance-tests.md) tách phần còn cần runner.

## 2. Nguồn và quyền quyết định

| Mã | Nguồn chính xác |
|---|---|
| Đ | [Đề PDF](<../temp-repo-for-agent/docs/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>), C.4–C.5 tr.6–7; F tr.9; A tr.11–13; B tr.14 |
| DC | [Điều chỉnh](sources/btc/DIEU-CHINH-DE.md), §1 latency, §3 tools, §4 handoff, §5 RQR, §6 Call Brief, §7–9 RAG/ASR, §10 ngày, §11 hard case, §12 simulator/judge |
| GD | [Giải đáp mentor](sources/btc/GIAI-DAP-MENTOR.md), Team 5 câu 11 RQR; Team 8 câu 3 CTC |
| SC | [Scenario format](sources/btc/schemas/scenario_format.md), bảng call_n và success_if |
| TR / CB / HB | [Trace](sources/btc/schemas/trace_log.schema.json), [Call Brief](sources/btc/schemas/call_brief.schema.json), [Handoff Brief](sources/btc/schemas/handoff_brief.schema.json), JSON Pointer /required và /properties |
| T / MO | [Tool descriptions](sources/btc/schemas/tools.schema.json), các tên tool; [mock_tools.py](sources/btc/eval/mock_tools.py), hàm tương ứng |
| E | [Scorer](sources/btc/eval/reference_eval.py): repeat_question_rate, context_carryover_rate, check_call, task_success_rate, hallucination_rate, latency, wer_cer, rag_eval, main |
| J | [Rubric](sources/btc/eval/llm_judge_rubric.json), /criteria, /judge_prompt_template, /agreement_protocol |
| L | [Latency](sources/btc/eval/huong-dan-do-latency.md), Định nghĩa và Quy tắc 1–7 |
| SIM | [Simulator](sources/btc/simulator/customer_simulator_spec.md), §1–5; [personas](sources/btc/simulator/personas.json) |
| ASR / RAG | [ASR](sources/btc/asr/ground_truth.json), /normalization_rule và /dialogues; [RAG](sources/btc/rag/qa_labeled.json), /questions |
| R | [README BTC](sources/btc/README.md), PUBLIC/Giữ lại/Quy trình chấm chéo |

Ba schema TR/CB/HB được giữ **nguyên byte** trong sources/btc. [sources.lock.json](sources.lock.json) ghim SHA-256 của 46 file nội dung BTC; không tính .DS_Store. T không phải JSON Schema thực thi, SC là văn bản: Scenario/ToolArgs và mọi schema nhóm đều **[NHÓM] chuyển đổi**, không phải schema BTC phát. Giữ wire ASR/RAG/report BTC; metadata nằm sidecar. Không truyền metadata nhóm vào scorer như thể BTC đã định nghĩa.

Tranh chấp B01–B15 ở §9: không sửa GT/scorer, không loại ca khỏi mẫu số để làm đẹp số. Tranh chấp ảnh hưởng release → giữ candidate.

## 3. Ma trận producer → consumer

Đường dẫn lưu dưới `runs/<run_id>/<config>/` trừ khi ghi khác. Đây là **[NHÓM]** layout, không phải yêu cầu tên folder BTC. ID toàn cục = run/config/scenario/call/turn; tool thêm event_id, judge thêm criterion_id/attempt; call-level dùng turn=1 làm khóa neo nhưng không có nghĩa evidence chỉ gồm lượt 1.

P4 score revision: snapshot P3 dưới evidence/, official-report.json giữ nguyên bytes BTC CLI; supplemental-report/validation/coverage theo schemas, scorer-invocation lưu argv/source hash/wrapper hash/stdout/stderr/diagnostic_only. Official report lỗi/missing không được thay object giả. Typed assertions tool_args dùng named request theo ToolArgs (name+args). Tool labels/profile/PII/judge/GT chưa đủ giữ INCOMPLETE; state verifier hiện dành mock BTC, không chứng minh database sản phẩm đúng.

P2 hiện có staging `raw-execution.jsonl` và `adapter-N.log` mỗi config, cùng `tools.jsonl` theo ToolEvent. Run-level có manifest/preflight/execution-plan/runner-report, verified bytes dưới `inputs/`, BTC source lock với base `inputs/`, hash file đóng trong artifacts.lock. Raw lifecycle/transcript/brief/memory/timing/usage chưa tự thành artifacts typed dưới đây: collector P3 đã chuyển/validate/provenance offline từ raw; không sửa raw hoặc chạy Agent lại để giả evidence thiếu. JSONL refs giữ pointer rỗng; source strings dùng normalized JSON documents/pointers thật. Fixture extractor không thay model/runtime/human audit. Runner-report staging không phải SupplementalReport/quality PASS.

| Artifact / schema | Producer → consumer; thời điểm | File | Khóa / xử lý lỗi |
|---|---|---|---|
| Scenario, ScenarioCall, SuccessIf | Người làm dataset → preflight/runner/scorer; trước run | dataset/*.json | scenario_id, call; unknown success_if chưa hỗ trợ → INCOMPLETE, không bỏ qua |
| Manifest, PlannedCall, Suite | Orchestrator → tất cả; ghim trước run | manifest.json (run-level) | run_id; sửa cấu hình → run mới |
| AssetRef, SourceLock | Người đóng gói → validator; trước run | sources.lock.json, refs trong artifact | path + SHA256 byte gốc + JSON Pointer; thiếu/hash lệch → INCOMPLETE |
| GradingContract | Người thiết kế test → supplemental grader; trước run | grading/*.json | scenario hash + call; success_if chỉ là reference, không tạo đáp án thứ hai |
| Trace nguyên bản TR | Agent adapter + extractor → E; mỗi lượt | full.jsonl / baseline.jsonl | trùng/thiếu ID → lỗi coverage; bảo tồn raw |
| ToolRequest, ToolArgs, ToolEvent | Adapter → trace/extractor/checks; trước/sau tool | tools.jsonl | event_id; args hợp lệ không chứng minh thành công |
| CallBrief nguyên bản CB + BriefEvidence | Memory/runtime → call mới/QA; khi nhận diện khách cũ | briefs/*.json + brief-evidence.jsonl | kind=call_brief, thời gian nhận diện→ready; phân biệt object sai và không thu được |
| HandoffBrief nguyên bản HB + BriefEvidence | Agent → consultant/QA; ngay khi chuyển người | handoffs/*.json + brief-evidence.jsonl | kind=handoff_brief; lấy working context hiện tại, không dùng CB cũ thay thế |
| MemoryFact, MemoryEvidence | Memory adapter → checks; before_call/after_turn/after_call | memory.jsonl | namespace + customer_id + key; wrong profile/value/supersede → FAIL nếu chứng minh được |
| Extraction | Extractor → trace/checks; sau transcript/tool log | extraction.jsonl | vị trí quote, speaker, slot/value; thiếu coverage extractor → INCOMPLETE |
| TimingEvidence | Backend → metric adapter; mọi lượt, kể cả warm-up | timing.jsonl | timestamp + usage + currency; không lấy UI clock thay backend |
| AsrHypotheses, Segments | ASR/diarization → E; sau audio | asr/hypotheses.json, audio/*.segments.json | dialogue ID; thiếu audio/GT/hypothesis không coi là 0 lỗi |
| AsrEvidence, SuiteEvidence | Adapter suite → QA/report | suite-evidence/*.json | raw→normalized→ITN/version; metadata không nhét vào wire BTC |
| RagResults, RagChunkMap | Retrieval/answer adapter → E/judge | rag_results.json, rag-chunks.json | qid/chunk ID; mapping phiên bản/ngày/restricted phải giữ |
| SimulatorLog | Simulator → riêng simulator report | simulator/*.jsonl | scenario/call/persona/seed; không trộn fixed-turn |
| JudgeVerdict, JudgeRecord | Judge + wrapper → supplemental report | judge/*.jsonl | raw chỉ PASS/FAIL; ERROR ở wrapper, không giả verdict |
| HumanAgreement | Người chấm → agreement report | human-agreement.json | call×criterion; ít nhất 20 cặp có cả hai nhãn theo J |
| ExpectedToolCalls | Người gán nhãn → Tool Accuracy | tool-expectations.jsonl | context; nhãn chốt trước run, không suy ra từ tool thực gọi |
| Coverage, Issue, ValidationReport | Collector/validator → scorer/release | validation.json, coverage/*.json | expected/observed/missing/duplicate/unknown; không im lặng rút mẫu số |
| OfficialReport | E nguyên bản → report adapter | official-report.json | giữ nguyên trường, hash report gốc; synthetic BTC sample không phải kết quả thật |
| Metric, SupplementalReport | Adapter/checks → report/release | supplemental-report.json | công thức, đơn vị, cohort, denominator, evidence; null có lý do |
| ErrorRecord | QA/checks → casebook/Source Gate | errors.jsonl | error_id + context + provenance; không tự cho phép học |
| Comparison | Report adapter → A.6/release | comparison.json → table.md | baseline/system cùng dataset hash; undefined delta giữ null |
| SourceDecision | Source Gate → evidence pool/Growth | source-decisions.jsonl | nguồn + quyền dùng; Frozen/hidden không auto-learn |
| Candidate, ApprovalRecord | Improvement/reviewer → evaluation/release | candidate.json, approval.json | version + content hash; review không phải benchmark |
| ReleaseDecision | Release gate → KB/version store | release.json | đúng candidate đã duyệt/đo; thiếu evidence giữ hold |

**Required/nullable:** máy đọc schema là nguồn chuẩn, không suy ra từ bảng. TR không required facts_used/memory_writes, nhưng applicability cần kiểm thêm: call có must_carry_over phải có evidence trích fact; có memory_expectation phải thu write/snapshot. CB/HB dùng đúng /required BTC; HB customer_name/product_advised/price_quoted_vnd nullable nhưng vẫn required. Kết quả tool là raw JSON bất kỳ vì BTC không phát result-schema: wrapper ToolEvent typed; thành công cần kiểm ngữ nghĩa từng tool, không suy đoán từ JSON parse.

Đối với trường mở trong wire BTC (args/result/facts/seed_history), không ép shape chưa được BTC chốt. Nhóm phải đăng ký slot/type/tool kết quả theo catalog + signature MO; field mới chưa hiểu đi vào lỗi mapping, không tự gán PASS.

## 4. Lifecycle và state

1. Validate schema + lock + IDs + grading + suite applicability; đếm scenario/call/turn dự kiến, audio ID, qid. M1 chính ≥20 đa phiên +5 khó theo cách đếm bảo thủ của nhóm; M2 ≥40; B12 chưa chốt nghĩa “20+5”. Chưa đủ thì vẫn cho development run, không official PASS.
2. Tạo namespace riêng cho **mỗi scenario/config**; seed nghiệp vụ một lần. Copy mutable orders/callbacks/tickets/promo usage của MO, không dùng chung singleton. Seed_history/CRM sessions chỉ nạp một lần; giữ state nghiệp vụ xuyên call.
3. Baseline chỉ chặn quyền **đọc memory hội thoại phiên trước**: cả ledger, CRM sessions, Call Brief/precomputed summary, cache và KB sinh từ chính test. Vẫn có working context trong call và state nghiệp vụ như đơn đã tạo. Model/prompt/tool/catalog/hardware/input của hai nhánh giống nhau; chỉ memory-read gate khác.
4. Call date: call_date nếu có; nếu không lấy ngày trước + days_later; call_1 nền 2026-10-15. Truyền on cho signature MO có hỗ trợ, lưu ngày trong ToolEvent cho mọi tool; B13 không truyền keyword vào hàm không nhận.
5. Có customer_turns_asr thì feed chính bản đó, không thay bằng clean transcript; giữ clean làm reference. Chiều dài cặp lệch → preflight INCOMPLETE. Fixed-turn chạy đủ kế hoạch, không giới hạn 12 của SIM.
6. Handoff dùng working context tại lúc chuyển, raw consultant answer giữ role riêng. Hết call chờ after_call hoàn tất hoặc timeout trước call sau; không “sleep một khoảng rồi giả sử memory xong”. Snapshot before/after gắn customer_id.
7. Thu raw evidence → validate cấu trúc/coverage/semantics → E nguyên bản → supplemental checks/judge theo suite → report → release. Nếu vẫn chạy E để chẩn đoán trên trace thiếu, phải gắn INCOMPLETE và không dùng cờ E làm PASS release.

**Timeout [NHÓM]:** bắt buộc manifest timeouts_ms cho agent/tool/after_call/judge; ví dụ 60s/30s/60s/60s chỉ là cấu hình fixture, không phải ngưỡng latency BTC. Timeout không chứng minh khách từ chối hay tool business FAIL. Không tự retry Agent/tool (side effect có thể đã xảy ra); thu reconciliation evidence hoặc review. Judge output hỏng được sửa đúng 1 lần, lưu cả hai attempts; failure sau đó INCOMPLETE. Khởi động run lại dùng run_id/state mới, không overwrite run cũ.

## 5. Extractor: quy tắc chuyển đổi, không tự chấm điểm

[TR /properties/questions, facts_used, claims; E repeat_question_rate/context_carryover_rate/hallucination_rate]

| Nội dung gốc | Kết quả chuyển đổi | Không được làm |
|---|---|---|
| “Phòng chị bao nhiêu m²?” | question slot=room_area_m2, type=open | Không dựa dấu ? để kết luận confirm |
| “Vẫn phòng 25 m² đúng không ạ?” | confirm, value=25 ở Extraction | Không tính confirm lần hai như lần đầu |
| “Máy 5 triệu, giao 2 ngày” | hai atomic claim price_vnd=5000000; delivery_days=2, cùng evidence span được phép | Không gom thành claim mơ hồ “tư vấn đúng” |
| “Phòng 25 m² thì chọn mẫu nhỏ” | facts_used room_area_m2 + Extraction.value=25, customer/profile/source rõ | Không đánh dấu fact chỉ vì xuất hiện trong memory |
| Tool args room_area_m2=30 nhưng GT=25 | raw args giữ 30; E có thể vẫn tính slot; supplemental fact_value FAIL | Không sửa trace về 25 cho đạt CCR |
| Consultant nói giá, agent chỉ chuyển máy | role=consultant, không thêm claim vào agent_text | Không gán chất lượng lời consultant cho Agent |
| Tool returns price=5 triệu | ToolEvent.result, không là claim Agent nếu Agent chưa nói | Không coi gọi đúng args là tool thành công |

Offsets start/end là **Unicode code point**, [start,end), tính trên đúng source string (AssetRef.pointer); quote phải bằng lát cắt đó. JSON Pointer tham chiếu JSON; JSONL dùng path + pointer rỗng rồi Context xác định dòng, không tự chế JSON Pointer theo số dòng. Thu reference câu khách/agent/tool đúng ID; extraction version + prompt/model được ghim. Phát hiện khó/ambiguous → Issue extractor, review; không gán value từ GT vào lời nói thiếu. Chuẩn hóa money thành VND integer, diện tích thành số m², phone thành chuỗi giữ số 0; không đổi nghĩa tự động.

## 6. Grading theo call

official_success_if trỏ thẳng /calls/call_n/success_if của file scenario đã hash; thiếu success_if thì null. **Mọi mode đều giữ scorer BTC**. assertion_only / judge_only / hybrid chỉ điều khiển phần bổ sung; Hybrid AND là [NHÓM].

Rule selector ghim trước run, JudgeRecord ghi quyết định thực tế:
- J02/J06/J08: all.
- J01: call_2+ (không sửa pass_if); xác nhận ≥1 sản phẩm/rào cản phiên trước, không quá3 thông tin cũ.
- J03 conflict; J04 identity mismatch/shared phone; J05 handoff case.
- J07 order.create present; ngoài selector, scenario kỳ vọng tạo đơn mà không tạo vẫn phải fail assertion, không thoát vì J07 N/A.
- J09 CCCD/STK; J10 hỏi AI; J11 vượt budget/COD; J12 hết hàng theo ngày gọi.

Scenario-driven condition được định nghĩa bằng tags/ground truth trước run; trace-driven condition như order.create dựa raw ToolEvent/Trace. Không thấy evidence cần để quyết định → INCOMPLETE, không tự cho N/A. Raw criterion IDs phải đúng J /criteria/*/id. Prompt gồm scenario, transcript, selected rubric, GT/source cần thiết; không cho judge đoán giá. Không sửa rubric BTC để tăng agreement.

Schema validate được mode/aggregation/enum; không chứng minh quote đúng, source phù hợp, applicability hay judgment chính xác. Nhãn reviewer giữ riêng HumanAgreement. J yêu cầu ≥20 cặp ngẫu nhiên, kappa **hoặc** %agreement; nhóm có thể báo cả hai.

## 7. M2 và evidence riêng

- ASR: hypotheses ID keyed, text là raw recognition, entities sau ITN; E tự lowercase/NFC/bỏ dấu câu/gộp khoảng trắng. Giữ AsrEvidence raw/normalized/ITN riêng để kiểm tra. Không dùng normalized text thay raw rồi che lỗi normalization. WER/CER và entity độc lập.
- Diarization: GT audio/<id>.segments.json + hypothesis turns. Speaker A/C theo BTC; E lấy midpoint GT, chọn hypothesis đầu tiên chứa midpoint, so speaker. Không gọi là DER. Thiếu segments → incomplete suite, không bịa GT.
- RAG: ghim corpus/chunk→document/version/restricted qua RagChunkMap. Chạy đủ 60 qid của source RAG; E chỉ retrieval/abstain, answer/version do judge/người riêng. Fragment # được E bỏ khi so relevant_chunk_ids, giữ ID đầy đủ trong raw result.
- SIM: state và 8 quy tắc nguyên bản SIM §1–3, persona prompt BTC; cap12 lượt khách/call, 3 seeds (nhóm mặc định0/1/2), log mọi call/seed. Timeout hạ tầng ở ErrorRecord không biến thành outcome timeout nghiệp vụ. Report riêng mean/std/range; không dùng turns SIM thay fixed-turn.
- Tool Accuracy: ExpectedToolCalls do người gán nhãn độc lập trước run. Xem công thức trong report-schemas, không dùng args_match pass làm proxy tool success.
- Voice: TTFA bắt đầu VAD end-of-speech; TimingEvidence.request_at của voice phải là mốc này, của chat là backend request. concurrency_group ghép ít nhất2 phiên overlap có bằng chứng. M2 cần R0/R1/R2; R0 khi chưa có active là phiên bản ban đầu ghim hash.

## 8. Source Gate, review và release

Source Gate giữa QA và evidence pool, và nhánh FAQ, kiểm **nguồn/quyền học**, không kiểm giá, không quyết định nhập Frozen. Production/development/simulator được phép chỉ khi quyền sử dụng/PII rõ; Frozen/hidden report-only, mặc định deny learning. Public không tự động được phép học; cần quyết định ghi rõ mục đích. Unknown nguồn → pending, cách ly.

Mỗi call nếu chọn Reflection có lesson hoặc no-change; record theo SourceDecision/ErrorRecord/Candidate, không phải cứ sau call là publish. Candidate FAQ từ 6c và Reflection từ13 cùng review14 → eval15 → active16. 6c lưu draft, không live ngay. Growth là Scenario + grading + provenance/ref, không phải errors.jsonl; ca dẫn xuất Frozen giữ lineage, không quảng cáo là independent test.

Release [NHÓM]: approval đồng ý, candidate_hash=approved_hash=evaluated_hash, mọi suite áp dụng COMPLETE+PASS, không tranh chấp tác động, đáp ứng ngưỡng và no-regression đã ghim. R0 chưa có active → so baseline và ngưỡng; R1 so R0; M2 thêm R2. M1 không bị chặn bởi suite M2 N/A. Thay candidate sau PASS → evaluate lại. Rollback trỏ previous_version + reason/evidence, không xóa history.

## 9. Chờ BTC — không để implementation tự chọn đáp án

Các ID kế thừa E3 trong [flow](../evaluation-flow.md); file nguồn nằm trong sources/btc. Tranh chấp chưa có evidence BTC vẫn **OPEN**; B14 có scheduling **DEFERRED** theo user, không phải resolved. B01 count đã xác định từ file, chênh README chưa có changelog. Không tự sửa GT hoặc coi deferred là BTC đã thống nhất.

| ID | Hai nguồn/điểm chưa khớp | Phạm vi và hành động |
|---|---|---|
| B01 | R inventory vs catalog/promotions.json và public_sample | Inventory actual; không dùng count README thay số file |
| B02 | SAMPLE-01 /calls/call_1/customer_turns vs /facts_established/budget_vnd | fact_value/J11/GT budget disputed, giữ candidate nếu liên quan |
| B03 | SAMPLE-02 call2 ground_truth_facts/promo_active vs promotions/MO ngày18/10 | Claim promo chưa đủ GT; không sửa raw |
| B04 | SAMPLE-03 success_if order ID vs crm_seed/MO order_create | Seed order phải xác nhận, không fake ID |
| B05 | RAG Q20 expected answer vs BH-01/catalog Xiaomi | Answer/version chưa đủ GT, retrieval vẫn báo riêng |
| B06 | RAG Q57 expected10.435.000 vs MO pricing_get_quote tổng10.135.000 | Bundle promo exclusivity cần chốt; numeric answer hold |
| B07 | policy vận chuyển VC-03 vs QT-01/J11/MO | Đúng10triệu COD chưa chốt biên; không tự đổi enum/GT |
| B08 | playbook PB-01 tối đa2 fact vs J01 tối đa3 | Runtime≤2 nhóm chọn; judge vẫn rubric≤3 |
| B09 | L bỏ3 warm-up vs E latency không bỏ | Giữ report raw + derived, xác nhận protocol official |
| B10 | Đ A.6 turns/scenario vs E turns/call; Đ/GD Team8 Q3 CTC | Báo cả2 đơn vị; CTC ghi optional theo giải đáp |
| B11 | Đ M2≥100SKU vs products 40parent/96variant | Chờ cách đếm catalog; không tự thêm data |
| B12 | Đ “20+5” và SIM §5 độ lệch≤10 | Nhóm chọn20 thường+5khó; simulator báo cả std/range, gate range là nhóm |
| B13 | DC §10 mọi tool on vs MO signature | Truyền khi hỗ trợ, record ngày mọi event; không sửa MO |
| B14 | R nhắc validator/audio/segments vs46 file thực nhận | Chưa nhận; validator và audio BTC đầy đủ deferred theo user04/10/2026. Khai báo scope trước run, giữ yêu cầu để làm sau; không biến deferred thành PASS/N/A của BTC |
| B15 | Policy đổi trả cũ/lịch11-11 vs MO order_update/schedule_callback | Các case phí đơn cũ/giờ đặc biệt disputed; không sửa output mock |

B14 không ngăn scope hiện tại dùng ASR/diarization team và fixture tests; chưa đủ evidence audio BTC đầy đủ. Scope sidecar tham chiếu manifest sources ghi deferred, không tự đổi suite enum/expected IDs sau run. Không tuyên bố “mọi mâu thuẫn đã giải quyết” hoặc scope PASS là đầy đủ yêu cầu đề.

## 10. Cách đọc required/nullable tự động

Bảng dưới là required **cấp trên cùng** của từng $defs; nested required, conditional oneOf/allOf xem schema. Trường nullable phải hiện diện nếu trong required. Trường optional không có giá trị ≠ null. Trường {} chỉ dùng để giữ giá trị nghiệp vụ/raw JSON chưa có kiểu BTC, không phải bỏ qua semantic checks.

| $defs | Required cấp đầu | Nullable cấp đầu |
|---|---|---|
| AssetRef | path, sha256, pointer | — |
| Context | run_id, config, scenario_id, call, turn | — |
| Status | verdict, completeness, reason_codes | — |
| Suite | id, applicable, reason | — |
| SuccessIf | Xem oneOf / kiểu gốc | tool_called |
| ScenarioCall | customer_turns | success_if |
| Scenario | scenario_id, level, persona, hard_case, customer_phone, customer_name, honorific, notes, calls | hard_case, customer_name |
| PlannedCall | config, scenario_id, call, expected_turns, memory_required | — |
| Manifest | schema_version, artifact_id, run_id, level, fixture, purpose, split, created_at, round, reference_date, timezone, sources, scenarios, grading_contracts, suites, planned_calls, asr_ids, rag_ids, simulator_seeds, configuration, timeouts_ms, retry, state_namespaces, warmup_count, candidate_hash, dispute_ids | — |
| ToolRequest | name, args | — |
| ToolArgs | Xem oneOf / kiểu gốc | — |
| ToolEvent | schema_version, artifact_id, run_id, context, evidence_refs, event_id, request, on, started_at, finished_at, outcome, result, error, side_effect, attempt | error |
| BriefEvidence | schema_version, artifact_id, run_id, context, evidence_refs, kind, object_ref, identified_at, ready_at, producer, validation | — |
| MemoryFact | key, value, customer_id, source, valid_from, valid_until, state | valid_until |
| MemoryEvidence | schema_version, artifact_id, run_id, context, evidence_refs, customer_id, namespace, phase, facts, writes | — |
| Extraction | schema_version, artifact_id, run_id, context, evidence_refs, extractor_version, items | — |
| Segments | segments | — |
| AsrHypotheses | Xem oneOf / kiểu gốc | — |
| RagResults | Xem oneOf / kiểu gốc | — |
| SimulatorLog | scenario_id, call, persona_id, seed, patience_trace, outcome, n_turns, ended_by | — |
| JudgeVerdict | criterion_id, verdict, evidence | — |
| JudgeRecord | schema_version, artifact_id, run_id, context, evidence_refs, criterion_id, applicable, selection_reason, attempts, status, verdict, error, judge_version, human_verdict | verdict, error, human_verdict |
| Coverage | schema_version, artifact_id, run_id, scope, expected_ids, observed_ids, missing_ids, duplicate_ids, unknown_ids, status | — |
| Issue | code, artifact, json_pointer, message, classification | — |
| ValidationReport | schema_version, artifact_id, run_id, status, issues, coverage_refs | — |
| Metric | metric_id, formula_id, unit, value, numerator, denominator, cohort_ids, evidence_refs, status, reason, currency | value, numerator, denominator, reason, currency |
| SupplementalReport | schema_version, artifact_id, run_id, status, metrics, checks, coverage_refs, official_report | — |
| ErrorRecord | schema_version, artifact_id, run_id, context, evidence_refs, error_id, category, expected, observed, reason, source_split, learning_permission, root_cause, remediation, retest_ref | root_cause, remediation, retest_ref |
| Comparison | schema_version, artifact_id, run_id, dataset_hash, baseline_report, system_report, rows | — |
| ReleaseDecision | schema_version, artifact_id, run_id, level, decision, candidate_hash, approved_hash, evaluated_hash, approval_ref, suite_results, dispute_ids, reason_codes, previous_version | previous_version |
| OfficialReport | n_scenarios, system | asr |
| TimingEvidence | schema_version, artifact_id, run_id, context, request_at, first_token_at, first_audio_at, completed_at, brief_identified_at, brief_ready_at, warmup, audio_seconds, asr_wall_ms, input_tokens, output_tokens, cost, currency, concurrency_group, evidence_refs | first_token_at, first_audio_at, completed_at, brief_identified_at, brief_ready_at, concurrency_group; thêm audio_seconds/asr_wall_ms/input_tokens/output_tokens/cost/currency ở version1.1.0, legacy1.0.0 không nullable |
| SuiteEvidence | schema_version, artifact_id, run_id, suite, inputs, outputs, status, coverage, model_version, normalization_version, elapsed_ms | normalization_version |
| SourceDecision | schema_version, artifact_id, run_id, source_split, origin, permission, purpose, policy_version, reason | — |
| Candidate | schema_version, artifact_id, run_id, version, parent_version, content, source_decisions, growth_cases, kind | parent_version |
| ApprovalRecord | schema_version, artifact_id, run_id, candidate_hash, decision, reviewer, reviewed_at, policy_sources, reason | — |
| SourceLock | schema_version, files | — |
| RagChunkMap | schema_version, artifact_id, run_id, evidence_refs, chunks | — |
| AsrEvidence | schema_version, artifact_id, run_id, evidence_refs, dialogue_id, audio, ground_truth, hypothesis, raw_text, normalized_text, itn_entities, normalization_version, itn_version | — |
| ExpectedToolCalls | schema_version, artifact_id, run_id, evidence_refs, context, calls, allow_extra_read_only, labelled_by | — |
| HumanAgreement | schema_version, artifact_id, run_id, evidence_refs, pairs, sampling_seed, sampling_frame | — |
