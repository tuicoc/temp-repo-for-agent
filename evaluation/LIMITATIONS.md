# Evaluation — giới hạn và điều kiện gỡ

## Checkpoint JSON output (1) — 10/10/2026

- **L35 — DIAGNOSTIC_GT_PENDING_QA:** 5 scenario/12 call nguồn sinh có `success_if`
  scorer BTC bỏ qua, outcome ngoài enum, order GT không có trong CRM và hai hồ sơ
  chung số. Revision `datasets/output1-btc-diagnostic-v1` đã chuẩn hóa schema và
  viết lại assertion theo lời khách/BTC mock; 12/12 nhãn vẫn do nhóm diễn giải,
  chưa có QA duyệt. Ảnh hưởng: chỉ chấm diagnostic, không cấp M1/M2 acceptance.
  Gỡ khi QA duyệt từng call và tạo revision mới nếu nhãn đổi.
- **L36 — JSON_ONLY_NO_RUN:** `integration/output1-diagnostic-prepared-20261010-01`
  pin hai config, preflight 12 call/64 lượt dự kiến đạt; chưa có runtime trace,
  extractor, BTC score hay M2 producer evidence. Người dùng tạm hoãn ASR và không
  duyệt model API trong đợt này, nên không chạy sản phẩm thật hay tuyên bố các
  chỉ số được đo. Gỡ bằng run full/baseline cùng controls trên revision đã duyệt,
  collect/score và kiểm evidence. ASR là bước riêng sau đó.

## Checkpoint G0–G4 hiện hành — 09/10/2026

- **L27 — PARTIAL / PROVIDER_CONNECTIVITY:** Groq run cũ `m1-g0-groq-20261009-01`
  giữ nguyên lỗi `APIConnectionError`. Google run `m1-google-postgres-api-20261009-01`
  dùng 17/20 authorized attempts; 3/4 calls complete, full/call_2 dừng ở call budget 10
  sau nhiều lượt tra SKU. Execution incomplete; không tự retry/call thêm trong đợt này.
  JSON strategy/span fix đã có offline regression nhưng chưa live-smoke lại sau các thay đổi
  mới nhất. Hai revision Google mới `integration/m1-google-bounded-20261009-01/02`
  đã hoàn tất 4/4 call nhưng collector 0 trace: revision01 Brief thiếu field BTC;
  revision02 Brief đã hợp lệ nhưng signed final text bị `text_of` loại nhầm.
  Parser đã sửa và probe JSON hợp lệ; chưa chạy lại full collector sau fix.
  Tổng ngân sách mới đã dùng 39/40 attempts (18 + 19 + 2 probes), không dùng 1 lượt
  còn lại cho full run. Điều kiện gỡ: run revision mới với cap riêng và closed trace,
  rồi audit extractor; không sửa run cũ.
- **L28 — PARTIAL / POSTGRES_SANDBOX:** Compose `agent-evaluation` tại
  `127.0.0.1:55433/agent_eval_dev` chạy khỏe, chỉ local sandbox. Backend 57 tests đạt trong
  lần `--test`; gồm persistence/restart, namespace, lỗi barrier và web lifecycle với fake
  models. P2/P3/P4 adapter qua PostgreSQL cũng 3 tests đạt bằng model giả. Không phải live
  provider acceptance, multi-worker/cold-restart API recovery hay production rollout.
- **L29 — PARTIAL / M1_FUNCTIONAL:** G2 code đã có PII mask (trước model và persistent turns), ambiguous-identity isolation,
  deterministic routing/lane permissions, per-turn tool limits, field redaction và output
  guard; G3 web sandbox API/UI là opt-in (`EVALUATION_WEB_CALLS_ENABLED=1`) và evaluator
  gọi cùng `CallRuntime`. G4 có source-backed QA queue/review/HMAC approval/hash invalidation
  và explicit sandbox consumption. Legacy `/api/conversations` khi bật flag đã dùng runtime;
  call index bền qua restart và có QA reconciliation cho call gián đoạn; `benchmark-rounds`
  đã kiểm controls/hash và gọi P2→P7 scorer. Tuy vậy active graph chưa resume giữa turn,
  web multi-worker/cross-channel linking chưa nghiệm thu, R0→R1 thực chưa chạy qua scorer
  sau parser fix và chưa có release authority/consumption đầy đủ. Vì vậy không gọi
  M1 functional PASS hoặc M2 module live PASS.
  M1 acceptance chờ dataset chuẩn, live model/evidence, human labels, timing quota/audio và
  R0→R1.

Các checkpoint cũ dưới đây giữ để truy vết, không override các mục hiện hành trên.

Cập nhật: 09/10/2026, gói2product local runtime/adapter đã kiểm, P7release còn partial. Đây là sổ theo dõi **liên tục từ P6 đến khi hoàn tất implementation**, không thay contracts hoặc nguồn BTC. Agent ở mọi phase tiếp theo phải đọc file này và cập nhật giới hạn mới ngay khi phát hiện, kể cả giới hạn do code của nhóm; không chỉ ghi các dependency user còn thiếu.

**Loop gói3→P10 ngày09/10:** user duyệt tiếp toànsteps và đúng1subagent review. Đã nối realcommandextractor +P7release gates/packagecasebook +P8judge/agreement +P9/P10evidence components/CLI/handoff; **các phase vẫn partial, chưa architecturefullcomplete**. Trạng thái code hiện hành ở [architecture-status](architecture-status.md). Không dùng từ “P10hoàn tất” cho importerJSON hoặc fake-testPASS. Reviewer không gọiAPI/DB và khôngsửa files; parent fix findings cótests.

Checkpoint07/10: user đã mở lại implementation theo flow implement→check conflict→fix→phase sau. P6 bổ sung ledger/casebook importer và sửa float boundary RQR; P7 đã có diagnostic compare/readiness nhưng release integration còn chờ xác minh candidate/approval/authority. Không dùng phần comparison đã có để báo P7 hoàn tất hoặc tự active. Các limits nghiệm thu chưa gỡ bằng fixture tests.

Quy trình user chốt thêm07/10 khi nối product: thiếu→ghi rõ→giải pháp theo context→hỏi nếu cần→**chỉ implement khi user đồng ý**. Audit/read-only tests và ghi findings được tiếp tục; chưa sửa source product hoặc gọi provider. User đã cho thử2–3lượt API với model phù hợp, nhưng gói thay đổi integration vẫn chờ duyệt; không dùng quyền thử API để tự implement runtime còn thiếu hoặc truy cập DB production.

**08/10 user đã duyệt gói1:** đã implement Advisor tool/config injection và diagnostic subprocess bridge/root smoke. Product chat mặc định giữ nguyên; backend12tests đạt, bridge3tests đạt. Lần smoke thật dừng trước model vì thiếu key,0model calls. Đây là checkpoint lịch sử; trạng thái mới ở [CODE-HANDOFF](CODE-HANDOFF.md).

**Sau đó user duyệt tiếp gói2 (checkpoint09/10):** đã implement MemoryAgent/CallRuntime local và P2 product adapter, test P2→P3→P4 bằng fake models đạt. Các câu “gói2chưa duyệt” ở checkpoint cũ là lịch sử, không áp dụng cho việc tiếp tục gói2. Không cấp quyền chạy APIbenchmark lớn/DBproduction bằng lệnh tiếp tục code; gói3release/candidate/measurement chưa hoàn tất.

## Quy tắc cập nhật

- Mỗi giới hạn có ID, nguyên nhân, ảnh hưởng, cách xử lý/điều kiện gỡ và trạng thái. Phân biệt lỗi code với thiếu dữ liệu/quyền/runtime; không quy mọi việc còn thiếu cho user.
- Không xóa mục cũ khi đã gỡ: đổi trạng thái và link evidence/run mới. Không sửa report/run đã đóng để đổi trạng thái.
- Không mặc định giới hạn là blocker implementation. Tiếp tục phần offline/in-scope có thể làm; điều kiện nghiệm thu chưa đủ phải giữ INCOMPLETE/hold.
- Không dùng số0, timestamp giả, nhân bản fixture, miễn review ngoài scope hoặc sửa BTC/GT để gỡ giới hạn.
- Chỉ coi phase đã nghiệm thu khi đủ gate/evidence của phase đó. Code/test fixture chạy được khác benchmark sản phẩm thật đạt.

## Ledger lịch sử L01–L26

Các hàng dưới đây ghi lại giới hạn tại thời điểm P0–P10 ban đầu. Nhiều câu về
"chưa có product adapter/MemoryAgent/release gate" đã được thay bằng checkpoint
L27–L34 ở đầu file; không dùng chúng để suy trạng thái code hiện tại. Những
dependency còn thật (dataset, quyền, timing, audio, M2 producer) được tổng hợp
trong [CODE-HANDOFF](CODE-HANDOFF.md).

| ID / trạng thái | Nguyên nhân | Ảnh hưởng | Xử lý / điều kiện gỡ |
| --- | --- | --- | --- |
| L01 — OPEN | P6 dùng test adapter/fixture kế thừa P2, không phải Agent thật. Chưa tích hợp adapter sản phẩm, credentials, memory/DB/cache/KB namespaces và barrier runtime. | Chạy kiểm pipeline được; chưa chứng minh isolation, hiệu quả memory hoặc tốc độ sản phẩm. | Nhóm implement runtime adapter trên hooks đã có; user cung cấp cấu hình/môi trường/quyền khi đến integration. Chạy full/base cùng inputs/config, state riêng; không cần DB production để viết metrics offline. |
| L02 — OPEN | Fixture có2 raw turns/config, warm-up yêu cầu3; không còn mẫu hiệu lực. | Effective p95 INCOMPLETE; raw fixture timing không phải benchmark. | Thu ≥103 raw turns/config để có ≥100 mẫu sau3 warm-up. Không lặp bytes hoặc dùng timing ASR replay. Timing-repeat cohort riêng chưa implement; hiện dùng cohort fixed-turn thật đủ lớn. |
| L03 — OPEN | Fixture không có usage/tokens/cost/currency; policy P6 được pin trước run nhưng các giá vẫn null. | Tokens/call và cost/call INCOMPLETE, không phải miễn phí. | Pin giá đơn vị/currency vào manifest.sources **trước run mới**; runtime trả receipts với scope/pricing hash/component units đúng README P6. Không cập nhật giá vào run cũ. Giá và usage thực cần từ môi trường triển khai, không hỏi user để dựng fixture giả. |
| L04 — IMPORTER IMPLEMENTED / measurement OPEN | Ceiling04/10: chỉ run_turn receipts. Ngày07/10 đã có closed ledger importer bao phủ exact hooks/binding, failed charges, scope/hash/units/prices và reconciliation flag. Runtime/provider chưa xuất ledger thật. | Có ledger hợp lệ thì tính cả failed cost; không có hoặc chưa reconcile vẫn INCOMPLETE. Không tự đo/bịa billing hoặc sửa completion. | Producer theo [P6 evidence](p6-input-evidence.md); receipt authenticity/compute estimate cần deployment thật. Code đã kiểm bằng tests; legacy path vẫn giữ ceiling khi thiếu ledger. |
| L05 — OPEN | P3 fixture extraction chưa có model extractor và audit người đủ yêu cầu. P4 thiếu một số GT/tool expectations/PII labels; handoff/expectation prose chưa có semantics chốt. | P4/P6 giữ EXTRACTOR_AUDIT_PENDING và issues liên quan, không dùng BTC TSR100% để cứu lỗi fact. | Nhóm implement extractor/audit adapter; người có thẩm quyền cung cấp/duyệt labels, policy và audit evidence. Không miễn audit theo waiver review ASR. |
| L06 — OPEN / provisional | ASR dùng synthetic-v1 dev4/eval20; review0/20, Frozen/C.1 chưa đủ. User cho dùng tạm và bỏ review làm execution blocker riêng bộ này. | ASR replay20/20 chạy được, benchmark_ready=false; không nghiệm thu dataset thật/full BTC audio. | User bổ sung bộ đúng sau; tạo registry/version/GT/locks/settings/run mới và review theo yêu cầu. Giữ nguyên metadata unreviewed của bộ tạm. |
| L07 — OPEN / replay | P5/P6 replay transcripts Medium đã pin, không chạy inference mới. ASR là shared team cohort, không phải hai đo đạc Agent full/base. | Có raw/normalized WER/CER/entity; không có ASR speed mới hoặc suy TTFT/TTFA của Agent. | Chạy mode infer explicit trên model/dev lock hợp lệ khi được giao; đo backend riêng. Không tự tải model/TTS có phí. Scorer native không xuất edit-count WER/CER thì không dựng numerator giả. |
| L08 — IMPORTER IMPLEMENTED / evidence OPEN | Ngày07/10 đã có closed review importer bind exact source score/error, giữ provenance/learning permission, kiểm retest distinct raw/trace/run/refs. Chưa có ≥10 lỗi thật đã review/retest. | Fixture vẫn0qualifying; real reviews đủ quota mới analysis_complete=true. Reviewer identity là khai báo, không quyền release. | Người review cung cấp phân tích/retest theo [P6 evidence](p6-input-evidence.md); không tự sinh causes/duplicate quota/Growth. Authority release còn L13. |
| L09 — DEFERRED_BY_USER | Chưa tích hợp validate_scenarios.py và audio/segments BTC đầy đủ theo quyết định user. | Không chặn scope tạm đăng ký, nhưng btc_full_readiness luôn INCOMPLETE; không gọi deferred là PASS/N/A toàn đề. | Chỉ mở lại khi user yêu cầu và có nguồn BTC hợp lệ. Missing trong cohort đã đăng ký vẫn là lỗi coverage, không thuộc defer này. |
| L10 — PARTIAL | P7 diagnostic R0/R1 comparison/no-regression/readiness đã có07/10; release còn chưa tích hợp. P8–P10 chưa implement. | Không có ReleaseDecision/active production; evaluation chưa toàn bộ đề. | Hoàn thiện P7 khi có authority/consumption contract L13, rồi tiếp P8–P10. Applicable suites chưa hỗ trợ vẫn INCOMPLETE. |
| L11 — OPEN / portability | Một số ASR settings/dev-lock/evidence lịch sử có absolute paths máy tạo; model/venv không lên GitHub. | Clone khác máy chưa đảm bảo chạy replay/infer ngay với settings hiện tại. | Tạo settings/registry mới đúng root máy đích, cài requirements; không sửa bytes của lock/run cũ. Kiểm preflight trước chạy. |
| L12 — OPEN / storage ceiling | Snapshot immutable sao chép input/audio và closed runs qua các stage, chưa có content-addressed storage/dedup. | Benchmark fixture P6 hiện khoảng129MB/run; nhiều lần chạy tốn disk dù không gọi model. | Giữ evidence độc lập/hashes hiện tại. Chỉ thêm dedup/retention khi cần và có chính sách recoverable; không tự xóa runs user. |
| L13 — OPEN / P7 integration choice | Chưa có contract runtime tiêu thụ candidate R1, nguồn candidate/approval/version và cơ chế xác minh reviewer có quyền. Hiện chưa có R1 sản phẩm thật. | P7 comparator luôn staging hold; không dựng approval_ref/hash giả để xuất typed ReleaseDecision, không lấy tên reviewer tự khai làm authority. Chưa qua gate P7 để gọi phase sau hoàn tất. | User/nhóm sản phẩm chỉ rõ module/API/files quản lý candidate/approval, ai có quyền duyệt và cách evaluator xác minh; cung cấp R0/R1 thật cùng Frozen/config khi chạy nghiệm thu. Nhóm implement authority/hash/consumption/source gate theo thông tin đó. |
| L14 — OPEN / producer trust | Billing/review sidecars là declarations từ producer tin cậy; hash/shape/context đúng không chứng minh nguồn provider hoặc review con người thật. | Importer kiểm integrity/arithmetic, không authentication. Evidence mới không xóa issues P3/P4 lịch sử; fixtures không thành benchmark. | Deployment cung cấp producer/verifier có thẩm quyền và run mới; không thêm cờ verified=true để lách trust boundary. |
| L15 — OPEN / P7 package gates | Casebook importer P6 bind errors của một source run. Gate release cần tổng hợp errors R0 +review/retest R1 ở cấp package, không bắt R1 sạch phải tự có10confirmed FAIL mới đủ casebook. P7 package aggregation này chưa implement. | Per-run CASEBOOK_ANALYSIS_PENDING không được âm thầm xóa; cũng không thể dùng R0 bị FAIL làm release PASS. Comparator hiện hold, chưa cấp release sai. | Nhóm implement package casebook gate/provenance cùng P7 authority/consumption; giữ nguyên per-run reports và liên kết lỗi R0 với retest R1 thật. Đây là phần code nhóm còn phải làm, không yêu cầu user tạo10lỗi ở R1. |
| L16 — OPEN / product runtime | Read-only code audit07/10: backend chỉ có BaseAgent/AdvisorAgent. Advisor.tools() trả[], chat gọi invoke(history); DB chỉ users/conversations/messages. Chưa có MemoryAgent/Orchestrator, identity resolution khách, lifecycle đa phiên/barrier/snapshots/briefs. | Adapter đơn thuần không thể biến chat history20messages thành memory M1 hay chứng minh baseline isolation. P2 sẽ reject nếu thiếu capabilities; không khai capabilities giả. | Gói integration đầu tái sử dụng Advisor/factory và bind tools BTC trong môi trường riêng. Runtime M1 phải implement trong product hoặc nhận từ nhóm kiến trúc ngoài; user chốt ownership trước implementation. Không xây Agent thay thế trong evaluator. |
| L17 — OPEN / real extraction | Collector chỉ khởi tạo FixtureExtractor; descriptor chỉ fixture_replay và real/official manifest bị reject. | Advisor thật dù trả lời được vẫn chưa tính được questions/claims/fact-use để chấm toàn pipeline. Echo annotations không dùng cho câu mới, regex không giả làm model extractor đạt audit. | Gói sau bổ sung pinned real extractor/evidence validation/audit workflow trong evaluation. Tách chi phí extractor khỏi Agent; giữ audit pending cho tới có human labels thật. Smoke2–3model calls chỉ chứng minh wiring, không full P3/P6 acceptance. |
| L18 — OPEN / telemetry + environment | SSE ttft hiện đo filler; callback missing usage fallback0, token ledger process-wide. Backend .venv có LangChain nhưng thiếu jsonschema; ASR/evaluator env riêng. | Không dùng UI filler làm TTFT hoặc process totals làm cost/call; không đảm bảo runner spawn import được product dependencies trong environment hiện tại. | Bridge xuất nonstream TTFT=Total thật, usage unknown=null và per-hook counters; failed cost cần ledger reconciliation. Sau duyệt dùng environment integration riêng với requirements product + evaluator, không sửa ASR environment/dev lock, không tự dùng giá YAML0 làm free compute. |
| L19 — OPEN / API smoke | Read-only provider checks08/10: Google/Groq/NVIDIA keys đều chưa cấu hình. Smoke product-smoke-20261008-01 dừng ở startup,0model calls. | Gói1 đã kiểm graph/tools/IPC/budget offline, chưa có provider responses/timing/usage thật. Không tuyên bố Agent API smoke PASS. | User đặt GOOGLE_API_KEY cho default Advisor trong backend/.env hoặc environment; không gửi key vào chat. Sau đó chạy lệnh smoke với output mới, trần3model attempts. Không cần DB production. |
| L20 — OPEN / runtime local ceiling | Gói2 đã có local SQLite MemoryAgent/lifecycle/barrier/read gate/P2adapter; web chat và PostgreSQL deployment chưa dùng runtime này. Store in-memory không giữ sau restart; fixed SALES code coordination chưa OrchestratorAgent/routing đầy đủ. | Có thể kiểm process isolation/multi-session trong một run, chưa production persistence/multi-agent architecture đầy đủ. | Nối deployment storage/jobs/web lifecycle và router/guards; không tự chạy DB migration. Gói2tests không đủ nghiệm thu L01/S19. |
| L21 — OPEN / context +identity |7fact slots, raw episodic transcript, address TTL180ngày. Shared-phone/channel resolution, seed-history/CRM historical import, structured products/quotes/KMrefresh, full PII/guard/handoff timestamps chưa implement. | Ambiguous/seed nonempty reject, không đoán source/identity. Warning không chứng minh refresh; promptpolicy không chứng minh safety. Chỉ synthetic inputs được chuẩn bị. | Mở rộng ở product với typed provenance/security/refresh/budget tests; realdata chưasanitize không gửi model. Memoryquote đúng còn cần semantic audit. |
| L22 — REAL_EXTRACTOR_IMPLEMENTED / AUDIT_OPEN | command_model descriptor/process/collectorbranch đãcó, dependencies/prompt/modelversion pin trước run; rawattempt/timeout/span/role/budget kiểm, không đổi fixture extractorhash. Humansemantic audit chưa có/importworkflowchưa hoàn thiện. | Có đường chạy model thật khicredentials/budget; không chứng minh extractionaccuracy/coverage bằng emptyitems hoặc fixture annotations. | Producer/providerconfig+humanlabels/reviews thật; giữ EXTRACTOR_AUDIT_PENDING đến đủaudit. Chi phíextractor namespaceharness, khôngAgentcost. |
| L23 — P7GATE_IMPLEMENTED / LIVE_AUTH_OPEN | release-gate kiểm actualbytes/HMACapprove/policy/pins/roundcontrols/rawthresholds/consumptioncoverage/signedR0casebook→specificR1retest. ReviewUI/serviceauth/keymanagement vàproductionactive-pointerintegration chưa có. M2suite/R2release chưa nối. | Missingauthority/R1/casebook/control/suite giữhold; evaluator khôngsinh humanapprove hoặc deploy. HMAC sharedservice không thay end-userlogin/audit. | Trustedhumanreviewproducer/actualcandidates/runs; implement authUI+versionlifecycle+M2release/R2/ablation. Không cung cấp key model là xong toàn P7. |
| L24 — P8PARTIAL | Rubricselector/rawmax2attempt/quote/turncoverage/hybridAND/random20pairs/agreementkappa cócode; suitebundle nhập rawproducerattempts. Livejudgescheduler/repairproducer/humanlabelauth/automaticP4judgeintegration chưa đủ. | Componentrecords cómetric thật trên importedbytes nhưngoverallruntimepending; không gradePASS từ thiếuconditionalsignals hoặcturns. | Nốiactualmodelrequests/audit/humanannotations; authorityđộc lập, khôngmodelchấmtaygiả. |
| L25 — P9PARTIAL | RAGBTCscorer+60qidcoverage, diarizationmidpoint/segmentscoverage, simulatorrulekernel/seedstats cócode. LiveRAGretriever/answergrader/diarizationinference/simulatorAgentrunner+classification/persona/no-oracle-leak proof chưa có. | JSONimports khôngnewinference; Q20/Q57answerdisputed, rulekernelkhôngfull8rulesacceptance. | Implementproduceradapters/runtime/index/version/answerlabels +actualseeds. Táchfixedturn/SIM metrics, khôngfeedGoldAgent. |
| L26 — P10PARTIAL | TCAreuse +voiceuniqueplannedturns/clock/overlap/quota +closedhandoff/R2presence/A01–A18missingchecks cócode. VoiceVAD/playback/concurrencydriver/storeisolation, R2improvement/ablation, liveacceptanceverifiers vàportablefresh-envpack chưađủ. | Namespace/played_audio label khôngproofphysicalbyte; duplicatedtimings khôngquota. Package vẫnINCOMPLETE/NOT_RUN hoặcUNVERIFIED, khôngcertificate. | Nốirealvoiceevents/instances/R0R1R2producer vàindividualacceptanceverifiers; không đổiapplicability hoặc fakeclock đểPASS. |

Review09/10 fixes: deadline-awarechunkreader thay readlinepartialblocking, shared terminate/wait/kill cleanup (cảSIGTERM), source-HMACkey khôngtruyền modelprocess; release khônggánP6reportPASS choM2suite chưađo, sharedcontrolled-change/costchecks; strictmandatorygateIDs/bools +rawratiosrange0..100 vàthresholds; sourcevalidationstatus/issues/provenancekhớp trướccasebookexception; specificR1retestbytes; consumptionactualresource/event/runturn/plannedcoverage; judgeexactturncoverage/sourceassertionreport; voiceuniqueIDs/clockduplicates/plannedwarmup/briefwithin session. Tests khóa negativecases; oldruns giữ nguyên.

Kiểm vònggói3-P10:126evaluator tests đạt quaCLIcheck saufixdiscoverypath/pattern;18backend+15ASR đạt. Review code khôngthayhumanapproval hoặcrealacceptance. Đã hỏi userPostgresstest/QAidentity vàproviderkeys/budget; chưa truy cậpprod/DB hoặccallAPI. Chưa cóquyếtđịnhmôi trườngtest/actuallabels/candidates, codegapsL20-L26khôngđượccoilàchỉthiếukeys. ArtifactnegativefixtureINCOMPLETEđượcgiữđúngtrạngthái.

Gói1 cập nhật L16/L18: Advisor đã nhận9tool schemas chuẩn, IPC tới isolated worker BTC; usage/timing đường diagnostic có nullable per-response counters/nonstream clocks, source/config/runtime snapshots và no-implicit-repair budget control. Không nối bridge này vào runner P2 với capabilities memory/barrier giả. Telemetry/chat cũ không bị thay và không được dùng làm measurement thật. L16 runtime đa phiên và L17 real extractor vẫn OPEN; hai interpreters dùng sẵn thay vì cài dependencies vào ASR environment hoặc backend. Producer cost/reconciliation vẫn L03/L04/L14.

Gói2 cập nhật09/10: L16 có implementation local cho snapshots/profile/episode/supersede/delete/baseline gate/commit barrier; P2adapter gọi hooks thật. L18có binaryIPC/hashsourcebundle/model-params check/per-hook callback usage, missing vẫn null. L20/L21 tách rõ phần chưa có; L17real extractor, L19credentials/budget và L13/L15release vẫn OPEN.107tests evaluator đạt; full regression giữ sourceBTC/run locks đúng. Không chạy thêm API.

Kiểm cuối09/10:107evaluator +18backend +15ASR tests đạt; whitespace diff và46BTC hashes/history locks đúng. Preparer chỉ tạo inputs development revision mới, không gọiAPI; casefull/sharedphone/seed/freshness/security chưa được nghiệm thu. Gói3chưa bắt đầu, không tạo candidate/approval/R1 thật từ scripted fixture.

08/10 revision02: [smoke](runs/product-smoke-20261008-02/smoke-report.json) startup blocked thiếu default provider key,0calls; handshake error không chứa provider body/credentials. Backend12tests và bridge3tests đạt; full evaluator regression105tests đạt trước thêm subprocess test thứ3, test bổ sung đã chạy riêng và đạt. Đã kiểm46BTC hashes, locks P6/P7 cũ và git diff whitespace; không sửa các thay đổi README/docs/dataset có trước ở product. Không push/deploy.

Đã fix07/10: lỗi số thực ở RQR đúng40% có thể bị so `<40`; calculation mới dùng Fraction từ raw numerator/denominator, regression test khóa exact40 và ca sát dưới40. Không sửa delta/report run04/10 đã đóng.

Read-only product check07/10: tìm candidate/approval/reviewer trong backend chưa thấy lifecycle/API tương ứng; `docs/engineering/SYSTEM_BASELINE.md` ghi improvement loop not-started và `IMPROVEMENT_RESEARCH.md` mô tả proposed→checked→approved→applied. Có callback/token ledger sẵn để tái sử dụng khi nối runtime, nhưng `extract_usage` fallback0 và process-wide agent totals không tự chứng minh usage từng hook/call; evaluator không được cắm thẳng missing0 làm measurements. Không sửa product trong turn này.

Kiểm tra07/10:103 tests evaluator +15tests ASR đạt; checker46source hashes và locks P2–P6 cũ nguyên vẹn. P6 mới5stages/error=null; P7 readiness hold. Không có R1/approval/provider billing thật, không push tự động.

## Product audit và các gói đề xuất — chờ user duyệt

Đã đọc source trong `../temp-repo-for-agent/`, không dùng sơ đồ để suy code đã có. Backend tests chạy07/10: `backend/.venv/bin/python -B -m pytest tests/ -q -p no:cacheprovider` từ backend,9passed; coverage hiện chỉ rate limiter. Product worktree có README/docs/engineering/evaluation changes từ trước, phải giữ nguyên. Không sửa flow.md/diagrams.md, secrets hoặc DB production trong audit.

**Không cần viết lại:** BaseAgent/create_agent ReAct, AdvisorDraft/Advisor._context, LLMFactory/provider config, rate limiter, token callback foundations, login/chat/SSE frontend, PostgreSQL users/conversations/messages, evaluator P0–P6/scorer/ASR/reporters. Dùng root `evaluation/` làm evaluator chuẩn; `temp-repo-for-agent/evaluation/` hiện chỉ có pilot dataset, không dựng evaluator thứ hai ở đó.

**Gói1 — nối phần có sẵn (đề xuất, chưa duyệt):** thêm boundary adapter từ root evaluation sang product; cho Advisor nhận toolset/config/callbacks có kiểm soát, không thay mặc định chat; bind tên/args BTC và giữ state nghiệp vụ trong isolated BTC worker. Thu actual backend timestamps, known/unknown usage, pin code/config/dependency provenance, budget tối đa3model calls kể cả ReAct/structured output. Test offline và smoke Advisor thật sau khi source changes được duyệt; không truy cập Postgres production hoặc gọi tools sản xuất. Chưa có runtime memory thì diagnostic/partial, không full M1 PASS.

**Gói2 — runtime M1 trong product (cần chốt ownership):** Orchestrator/MemoryAgent, identity/profile/episodic/supersede, start/turn/end-call, async barrier, snapshots/Call Brief, baseline read gate và cold/working state isolation. Tái sử dụng Postgres cho deployment nếu phù hợp; tests dùng storage/namespace riêng. Evaluator chỉ gọi hooks, không tạo facts/brief giả từ scenario GT.

**Gói3 — measurement và improvement:** real extractor/audit + đủ scenarios/usage/timings; nối proposal→checks→human review→candidate version/runtime consumption→R0/R1 compare/package release. Ưu tiên Knowledge Gap Loop M1; QA/Policy/Reflection/Exemplar mở rộng M2 theo đề/thiết kế, không tự coi chưa có Agent tương ứng là đã có chỉ vì schema/UI tồn tại. Phần BTC deferred vẫn giữ nguyên.

**Gate mỗi gói:** user duyệt scope → implement → component/integration tests +verify source/run hashes → báo conflict/limits; gói kế tiếp lại cần user đồng ý. Không dùng successful smoke/API response để tuyên bố toàn bộ evaluation đã hoàn tất.

## Mốc P6 đã chạy

- [Benchmark fixture mới07/10](runs/p6-fixture-benchmark-20261007-01/benchmark-report.json): kiểm stage order và báo cáo, không release. [Mốc04/10](runs/p6-fixture-benchmark-20261004-02/benchmark-report.json) giữ nguyên.
- [Bảng A.6](runs/p6-fixture-benchmark-20261004-02/metrics/table.md), [validation chi tiết](runs/p6-fixture-benchmark-20261004-02/metrics/validation.json), [casebook](runs/p6-fixture-benchmark-20261004-02/metrics/casebook.json).
- Fixture FAIL FACT_VALUE_WRONG_OR_UNUSED là evidence lỗi phòng30 so với GT25 kế thừa P4, không phải lỗi khiến runner không chạy. Pipeline error phải xem benchmark-report.error riêng.
- P6 không sửa product/DB, nguồn BTC, dataset/audio, model hoặc runs P2–P5 đã đóng; không tự push code mới.
- [P7 readiness07/10](runs/p7-readiness-20261007-01/round-readiness.json): thiếu R1 thực và authority/approval → hold, không comparison giả hoặc release.json giả.

## Việc cần đọc khi tiếp tục

README → file này → implementation plan phase được giao → contracts liên quan → code/tests → validation/report hiện hành. Gỡ giới hạn bằng evidence mới và cập nhật ID tương ứng ở đây; không ghi “đã đủ” chỉ vì unit tests PASS.

| ID | Trạng thái / nguyên nhân | Ảnh hưởng | Điều kiện gỡ |
|---|---|---|---|
| L30 | **PARTIAL / LEGACY_WEB_PATH:** khi `EVALUATION_WEB_CALLS_ENABLED=1`, `/api/conversations/{id}/messages` dùng chung `CallRuntime`, kết thúc call qua API và lưu chat đã mask; khi flag tắt vẫn dùng Advisor cũ. | Sandbox web/evaluator đi cùng lifecycle, nhưng chưa thay đường production mặc định hay chứng minh demo model thật sau đổi này. | Kiểm live trên sandbox với API budget mới, xác nhận UI/handoff và chỉ bật production sau security/load review. |
| L31 | **PARTIAL / KNOWLEDGE_GAP_REVIEW:** QA queue/dedupe, source pin, edit-hash invalidation, role/HMAC, UI, candidate consumption và outcome producer có provenance/idempotency. `benchmark-rounds` mới nối R0/R1 vào P2→P7 scorer, preflight controls/hash và giữ closed pair artifacts. | Chưa chạy cặp model thật sau đổi code; chưa chứng minh FAQ cải thiện trên Frozen. Web QA approval và evaluator release approval là hai payload khác nhau, không tự chuyển quyền. Diagnostic vẫn `hold`, không publish/activate. | QA chốt FAQ/source và approval đúng authority, hard cap API; chạy cặp thật, kiểm consumption/casebook và release gate trên Frozen đã kiểm. |
| L32 | **PARTIAL / WEB_SANDBOX_RUNTIME_CEILING:** PostgreSQL có durable call index/evidence; restart đánh dấu `RECONCILIATION_REQUIRED`, QA chỉ kết thúc khi không có tool outcome chưa biết. Active graph vẫn process-local, không resume model/tool giữa turn. | Không mất dấu call và không vượt barrier, nhưng multi-worker/concurrent retry, unknown side effect và cross-channel linking có xác nhận chưa được giải quyết. | Reconcile thủ công unknown outcomes dựa hệ thống nguồn; thêm worker coordination và linking workflow trước triển khai nhiều worker/production. |
| L33 | **PARTIAL / M2_FEATURE_FLAGS:** Reflection/Playbook đã được chốt làm cơ chế thứ hai. Judge batch có budget/repair; RAG có PostgreSQL FTS, public-only model producer, raw/resume và signed QA answer-review import nối vào suite bundle khi đủ ba asset đã pin; simulator có driver injected Agent; Reflection có source-gated records/3-call support. Chưa có module toggles wired vào product runtime hay live producer đầy đủ Judge/Simulator/Reflection. | Không thể bật/tắt từng M2 module và chứng minh revert về M1; JSON importer/partial live run không phải M2 acceptance. | Sau M1 functional regression, nối từng producer vào runtime/closed trace, default-off flag và OFF/ON/OFF regression; QA playbook/R2 mới được xét. |
| L34 | **OPEN / M1_ACCEPTANCE_DATA:** dataset tạm vẫn provisional; full corpus/audio/human review/timing quota chưa đạt. | Code functional không thể cấp M1 acceptance; P7/R0→R1 chỉ diagnostic. | Bổ sung bộ chuẩn và evidence theo plan; không sửa trạng thái provisional thành Frozen/human-reviewed bằng metadata. |
| L35 | **OPEN / LIVE_MODEL_QUOTA_AND_EVIDENCE:** M1 revision08 hoàn tất 4/4 call nhưng collector 0 trace do extractor rate-limit/format; deterministic fenced-JSON parser đã sửa, cần rerun. Unknown transport tool outcome cũng được sửa sau revision08, nên phải rerun actual adapter. M1 đợt24 đã dùng19, còn5 không đủ full revision; user chưa duyệt thêm. Google M2 RAG public-only có Q01–Q17 trên model đầu, Q01–Q09 trên model 3.6, tổng29/80 public transfers rồi quota. Groq probe Q01 hợp lệ; full same-model run đã dừng theo yêu cầu user khi ngủ giữa calls. Chỉ có manifest, chưa có attempts/results vì runner chưa checkpoint từng lượt; tổng M2 biết chắc 30/100 **trước** run dở, số lượt Groq run dở chưa đối soát. | Chưa có M1 full evidence, M2 RAG60/answer/version hay actual TCA transport recheck. Không dùng run dở để tuyên bố PASS hoặc tự suy ngân sách còn. | M1 cần hard cap mới được duyệt và revision riêng sau fix; không dùng ngân sách M2. Trước khi chạy Groq tiếp phải thêm per-attempt checkpoint, đối soát lượt đã dùng, rồi mới tạo revision mới trong hard cap được xác nhận; QA adjudicate Q20/Q57 và toàn bộ answer/version. |
# Checkpoint agent/prompt 10/10

Năm product agent đã có interface/prompt/schema. Revision hiện tại chuyển profile fact sang job `persist` sau call; working turns không ghi profile mỗi lượt, collector gắn writes sau call về đúng turn nguồn. Policy đứng sau hard guard, có tối đa một lần soạn lại nếu chưa có tool ghi; QA khi bật lưu verdict/UNDETERMINED riêng. Bundle đã cho pin flag Policy/QA và rubric BTC; mới predeclare J01 khi call_2+ và J02/J06/J08 cho mọi call, các tiêu chí có điều kiện khác vẫn do evaluator selector xử lý. Test hẹp product và bridge offline đạt; nguồn BTC hash-lock hợp lệ. **Chưa hoàn thành flow.md:** worker nền web, checkpointer/MCP role boundary, QA applicability đầy đủ, RAG hot path và Reflection active version. Chưa kiểm model thật, ASR hoặc chất lượng J01–J12; GT năm scenario vẫn diagnostic/chờ QA duyệt. Xem [architecture-status.md](architecture-status.md) trước khi tiếp tục.

