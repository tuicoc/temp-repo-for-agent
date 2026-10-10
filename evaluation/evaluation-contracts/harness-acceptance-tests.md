# Nghiệm thu contract và hành vi Harness

Version1.1.0. Thứ tự: schema → semantic fixtures → adapter/runner integration → benchmark thật. Nguồn viết tắt theo [ma trận](schema-contract-matrix.md#2-nguồn-và-quyền-quyết-định); công thức theo [báo cáo](report-schemas.md). **PASS của checker không phải PASS của Agent**. Scope hiện tại theo [README](../README.md): validator và audio BTC đầy đủ deferred; ASR team/coverage tests vẫn làm. A09 dùng team audio/fixtures, không chờ audio BTC để kiểm harness; không gọi đó là nghiệm thu BTC đầy đủ.

## 1. Những gì kiểm tra ngay được

Chạy `python3 check_contracts.py` trong môi trường đã cài requirements. Script chỉ đọc, không chạy tool/Agent/scorer và không ghi report benchmark.

- 5 JSON Schema được meta-validate: hai schema nhóm + ba schema BTC.
- Mọi $ref phân giải bằng registry local, không có network fallback; date-time qua FormatChecker, timezone bắt buộc khi format date-time.
- 51 ví dụ hợp lệ trong examples.json (gồm assertion-only/judge-only/hybrid, wrapper judge lỗi, TimingEvidence1.1 thiếu measurements và hai metric hiện hành); 18 mutation phải bị từ chối: required/type/enum/nullability/date-time/retry/ASR/RAG/SIM/hybrid, legacy Timing1.0 null, negative usage/cost và thiếu required nullable cost.
- Chuỗi fixtures M1: Scenario + Manifest + Grading + full/baseline JSONL + Call Brief + Handoff Brief. Không coi fixture này đáp ứng quy mô20/40scenario hay audio thật.
- Compatibility: 7 public scenarios +78 trace rows BTC +1 report_example =86 records; schema nhóm không siết sai các mẫu này.
- 46 source hashes/inventory khớp sources.lock.json; source BTC không thay đổi.
- Mẫu fixed-turn13 lượt **được** schema chấp nhận; FAIL+INCOMPLETE **được** giữ.
- 18 mutation ngữ nghĩa phải bị bắt: 15 phép bên dưới và3 phép S08 mới (TCA tính sai khi result lỗi, cost chia attempted thay completed, dùng formula tool-accuracy.v1 cho protocol mới). Positive formula fixtures cũng được tính lại. Đây là kiểm toán học trên fixture, không chứng minh tool matcher/runtime execution đúng.

| Mã | Fixture/biến đổi | Bước & kỳ vọng | Nguồn |
|---|---|---|---|
| S01_DUPLICATE | Append cùng trace row | So composite key; báo duplicate, không overwrite | TR IDs + nhóm integrity |
| S02_COVERAGE | Bỏ1row / coverage lists lệch | So manifest planned IDs, missing/unknown/duplicate; không complete | SC/TR + nhóm |
| S03_REFERENCE | Pointer /missing | Resolve path/pointer local; báo thiếu evidence | Nhóm provenance |
| S04_HASH | Hash đổi thành0 | SHA256 file bytes phải khớp | Nhóm versioning |
| S05_STATUS | PASS+INCOMPLETE | Reject tuple sai; FAIL+INCOMPLETE vẫn hợp lệ | Nhóm, report §2 |
| S06_STATE | Hai namespace trùng | Reject config isolation; plan full/base phải cùng scenario/call/turn | Đ A baseline |
| S07_TIME | Tool finish trước start | Parse timezone rồi so thời gian | L, nhóm event |
| S08_FORMULA | Metric MEASURED denominator0 | Reject; ratio/percent tính lại fixture | E pct + nhóm |
| S09_JUDGE | Applicable PASS nhưng verdict=null | Không cho PASS; wrapper lỗi riêng raw | J /criteria |
| S10_RELEASE | active nhưng hash đã đo khác | Hold; suite áp dụng cũng phải đủ result/pass/report | Nhóm release |
| S11_SOURCE | Frozen permission allow để learning | Deny auto-learning | Nhóm Source Gate |
| S12_GRADING | success_if trỏ nhầm call | So scenario ID, call set, đúng path/hash/pointer; không copy đáp án | SC + nhóm |
| S13_SUITE_COVERAGE | Manifest cần audio nhưng không hypothesis | So exact ID set; incomplete ASR | ASR/E wer_cer |
| S13_SUITE_COVERAGE | Manifest cần qid nhưng không result | So exact ID set; incomplete RAG | RAG/E rag_eval |
| S14_INPUT | Baseline customer_text khác full | Reject so sánh không cùng input | Đ A baseline |

Checker không dùng schema để khẳng định quote có thật, tính tool-success, approval của con người hay GT chính xác. AssetRef chỉ chứng minh file/hash/pointer tồn tại; **đúng vai trò nội dung** cần S15/A tương ứng dưới đây. Ví dụ cấu trúc trong examples.json không được chạy release.

P0 đã có [regression tests](../tests/test_p0.py), chạy `python -B -m evaluation.eval_harness check` từ workspace root: exact full/baseline scorer parity và report CLI mẫu, mock selftest subprocess, invocation matcher (business error vẫn TP, wrong args FP+FN), cost completed0/missing và timing nullable/legacy. Chỉ fixture/offline; không đánh dấu A01/A14/A18 hoặc S18 toàn bộ PASS vì còn thiếu runtime/coverage/collection/integration. Checker riêng vẫn chỉ kiểm contract, không gọi scorer/tool.

## 2. Semantic checks còn phải tích hợp vào harness

Các mục này **đã có hợp đồng nhưng CHƯA CÓ IMPLEMENTATION**. Không bỏ qua vì checker hiện xanh.

| Mã | Hợp đồng không thể giao JSON Schema tự chứng minh | Ca nghiệm thu |
|---|---|---|
| S15_CONTENT | Evidence đúng loại, đúng source string, quote=Unicode slice; raw tool result khác Agent claim | A03,A06,A18 |
| S16_APPLICABILITY | facts_used/memory_writes/brief theo call; judge selection đúng tags/trace; missing ≠ N/A | A02,A04,A07 |
| S17_TEMPORAL | Thứ tự call/turn, days_later cộng dồn, valid_from/TTL, after_call completion, backend clock | A04,A10,A12,A16 |
| S18_SCORER_PARITY | Report E nguyên bản/hash; mọi công thức bổ sung/rounding/cohort tính lại từ raw | A05,A08,A09,A10,A14,A18 |
| S19_REAL_ISOLATION | Namespace khác thật, không chỉ hai tên khác nhau; CRM/cache/KB không rò memory | A11 |
| S20_RELEASE_AUTH | Approval approve đúng content, role reviewer có quyền, hash bytes đã đo, đủ suite, no-regression | A13,A15 |
| S21_DATASET | Quy mô/split/ID, input ASR độ dài, call liên tục, tag hard, source rights/PII | A08,A09,A12,A15,A16 |
| S22_SIMULATOR | State+8quy tắc+seed+12lượt+no-GT-leak, fixed-turn độc lập | A12,A17 |
| S23_BUDGET | Token/đơn giá/currency/ASR duration, voice concurrency và độ trễ | A10,A14 |
| S24_RETRY | Side effect reconciliation, no implicit retry, judge repair1lần, artifact bị sai khác artifact bị mất | A01,A02,A07 |

Mã S01–S14 cũng phải chạy lại trên run thật với đúng scope; bản demo kiểm được quan hệ trong fixture, không chứng minh hạ tầng đã cách ly.

## 3. Ca hành vi A01–A18 — cần runner/adapters thật

P1 có14 component tests: process isolation/state xuyên call, baseline CRM filtering, signature/date injection, assets/root/hash, planned coverage/grading/suites/source/deferred/disputes. Chuẩn bị P2 thêm4tests cho execution gate, adapter/config/source pins và CLI. P2 thêm10fixture/fault integration tests:13turn noisy, seed once/provenance/no gold input, barrier ordering/timeout, baseline working context, live bind failures, raw invalid/partial, CLI/no overwrite, BTC state isolation xuyên call và lost reply sau commit không retry. `check` chạy chung68tests sau13tests P3 +13tests P4 offline (42 ở mốc P2). Preflight không import adapter/gọi model; P2 bind kiểm code/hook/signature/live declaration, không chứng minh external DB/cache/KB isolation hoặc SDK retry thật. Development dispute vẫn OPEN/INCOMPLETE dù gate cho thử bind; regression/official dispute và các issue khác chặn. A01/A04/A11/A12-fixed/A16 chỉ được kiểm các phần fixture nêu trên, không đánh dấu end-to-end PASS; collector P3 offline đã có nhưng còn cần runtime thật/model extraction/human review; P4 scoring offline đã có. SourceDecision/PII records được validate/pin, không thay human authorization thật.

Mỗi ca phải lưu input hashes, raw trace/events, validation, official/supplemental report và kết luận. Người triển khai đánh dấu NOT_RUN cho đến khi chạy thật; không đánh dấu PASS từ đọc mô tả.

| ID | Input / biến đổi | Bước thực hiện | Kết quả mong đợi | Nguồn |
|---|---|---|---|---|
| A01 Tool error dù args đúng | order.create khớp success_if nhưng result business_error; biến thể timeout sau commit | Chạy1lần, thu result/event/state; chạy E rồi supplemental | E có thể TSRpass; supplemental tool_success FAIL nếu business error. Timeout chưa rõ commit→INCOMPLETE, không retry tạo trùng | E check_call; MO order_create; nhóm retry |
| A02 Brief sai vs bị mất | HB bỏ customer_name (nullable nhưng required); lần khác collector mất cảobject | Validate raw HB; kiểm evidence retrieval | Có object sai→FAIL; không thu được→INCOMPLETE. CB không thay HB. Nếu đồng thời lỗi khác confirmed giữ FAIL+INCOMPLETE | HB /required, DC4/6 |
| A03 Fact đúng slot sai value | must_carry room_area_m2=25, Agent nói30; tool args30 | E CCR + Extraction.value + GT check | CCR có thể cao; fact_value FAIL. Tool value không được sửa về25 | E CCR, TR facts_used |
| A04 Memory sai khách / after_call trễ | Phone dùng chung, ghi fact sang hồ sơ khác; cố chạy call2 trước write xong | Snapshot by customer; await after_call; call2 chỉ bắt đầu sau barrier | Wrong-profile FAIL; timeout barrier INCOMPLETE. Seed chỉ1lần; supersede/TTL theo call_date | SC memory_expectation, CB, DC10 |
| A05 Claim thiếu GT / tranh chấp | Agent có claimfield không trong GT; biến thể B02/B03 | Giữ raw claim; E + GT coverage + dispute | E skip không tương đương đúng; supplemental INCOMPLETE. Không tự thêm GT/loạicase | E HR; B02/B03 |
| A06 Extractor/role | Câu 2atomic claims; confirm lặp; consultant trả lời nhưng Agent chỉhandoff; tool trảprice | Trích từ source spans, mapTR; audit quote/value/role | Không đếm consultant/tool là Agent claim; open/confirm đúng; trích thiếu→INCOMPLETE, khôngfake0questions | TR/E/J |
| A07 Judge lỗi | Model trảJSONhỏng2lần; biến thể không đủtrace để chọn J07 | Lưu raw2attempts; repair1lần; wrapper | verdict=null, UNDETERMINED+INCOMPLETE; không PASS/FAIL giả. Hybrid hardFAIL vẫn giữ. Bỏorder không thoát assertion | J + nhóm selector/retry |
| A08 RAG thiếu qid/version | BỏQ1 khỏi60; chunk#fragment; Q20 disputed | Verify IDs/mapping; E raw + answer/version suite | Coverage incomplete, không lấy recall E cao làm complete; Q20 answerhold, retrieval vẫn đo riêng | RAG/E rag_eval; B05 |
| A09 ASR missing | Bỏhyp1audio; thiếu segments; entitiesphone sai số0 đầu | Verify IDs/assets; raw→norm→ITN; E | ASR coverage incomplete; entities exact sai; diarization thiếu không gọi DER=0; giữ rawhyp | ASR/E wer_cer, DC8/9 |
| A10 Warm-up/latency | ≥100lượt,3lượt đầu có lỗi chất lượng; brief có refresh; voice2phiên overlap | Log backend clocks+usage; raw E và derived bỏ3; chấmquality tất cả | Lỗi warm-up vẫnđếm; raw/effectivecount rõ; brief gồmrefresh; voiceTTFA từVAD; M1 không chặn bởivoiceNA | L1–7/DC1; B09 |
| A11 State full/base dùng chung | Cho namespace khác tên nhưng trỏ cùng DB/CRM cache; tool ordersmutable global | Chạy scenariofull rồibase; kiểm sessions,orders,cache,KB và seed | Phát hiện leak, comparisonINCOMPLETE; đơn nghiệp vụ riêng nhánh nhưng xuyêncall. Baseline working context vẫn hoạt động | Đ baseline; MO globals; nhóm |
| A12 Fixed-turn >12 / SIM cap | Scenario13lượt; simulator persona patience/P0 và thứ tự8rule | Run riêng2mode,3seed | Fixed-turn đủ13; SIM≤12, log outcome đúng; không gộp mean vớifixed | SC, SIM1–5 |
| A13 Candidate đổi sau PASS | Version/hash đãapproved/evaluated rồi sửa FAQ1byte | Verify actualbytes +approval+manifest+report | Hold, khôngactive; phải review/eval lại. TestM1 vớiM2suite N/A không bị chặn | Nhóm release |
| A14 Metric math/cost | RQRbase0/full0; costUSD+VND; TCA invocation đúng/result lỗi; wrong args; cost failed calls; completed0; kappaPe1 | Tính raw theo registry, kiểm đơn vị/cohort | Reduction/kappa undefined; currency không cộng bừa; TCA invocation đúng/result lỗi vẫn TP, execution FAIL riêng; wrong args FP+FN. Cost gồm failed cost chia completed; completed0 undefined; thiếuprice/usage incomplete | E pct/main, J, nhóm formulas v1.1 |
| A15 Source Gate/Growth | ErrorFrozen, production cóPII, simulatorallowed; chưa cóactiveR0 | Kiểm provenance trước2nhánh6c/13; review14→eval15→16 | Frozenreport-only; unknownpending; sanitize/quyền trướcGrowth; noauto-live; R0thenR1/M2R2; derivative khôngindependent | Đ C5 + nhóm source/release |
| A16 Preflight/time/tool contracts | customer_turns_asr lệchlength; duplicatecall/ID; call_date override; MO khôngnhậnon; unknown success_if | Schema rồisemantic check, chặn chính thức hoặc markdisputed | Không sửa cleanfeed; khôngdropkey khônghỗtrợ; ngày theoSC; toolon đúngsignature; dataBTCgiữ nguyên | SC/DC10/T/MO; B13 |
| A17 SIM tái lập | 3seed cùng5cases, repeatedconfirm lần2, hallucinatedprice, unknownfacts, silence2/3turns | So ruletrace, persona state và prompt visibility | Đủ8rule, đủseed; mean/std/range; GTkhông lọtAgent; thiếuseedINCOMPLETE; rule8khácinfra timeout | SIM1–5 |
| A18 End-to-end report parity | Trace thiếu/trùng, evidence role sai, thiếu10lỗithực, human<20pairs | Validate→Eraw→supplemental→Comparison→release; recompute formulas | HashEđúng; nofalsePASS; turns/call≠turns/scenario; under20humanincompleteM2; under10casebookbáothiếu; fail vẫnhiệndiện dùcoverage thiếu | Đ A/F, J, E + nhóm |

## 4. Tiêu chí hoàn thành implementation sau này

- Chạy A01–A18 có evidence máy đọc, không chỉ tick tay.
- Schema mới/changed phải có positive và negative mẫu; tất cả $ref local; source hash vẫn khớp hoặc có phiên bản BTC mới có provenance.
- Mỗi suite có coverage expected trước run; raw không overwrite; lựa chọn nhóm và CHỜ BTC không trình bày thành BTC đã chốt.
- M1 suites: fixed-turn+baseline, data/trace/memory/handoff checks áp dụng, ASR, latency/cost/report và improvement theo flow. M2 thêm judge/human, RAG, diarization, SIM, toolaccuracy, voice/concurrency, R2. Cần applicability rõ cho từng kịch bản; không tự đổi sau khi thấy điểm.
- Mọi công thức registry có unit/mẫu số/test zero/missing/rounding. Evidence role/hash/time/profile kiểm thực, không chỉ string equality.
- Người khác copy nguyên thư mục `evaluation/` là mở được flow/PNG/contracts/sources và chạy checker sau khi cài dependency. Ba audit docs giữ làm mốc lịch sử; không coi chúng là bản flow mới.
