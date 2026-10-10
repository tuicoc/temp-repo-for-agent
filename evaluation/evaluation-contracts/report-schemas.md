# Báo cáo Evaluation — hợp đồng v1.1.0

Quyết định hiện hành theo [README](../README.md#1-quyết-định-hiện-hành--04102026). Formula mới tool-accuracy.v2 thay v1, không đổi báo cáo lịch sử. TimingEvidence 1.1.0 hỗ trợ measurement thiếu bằng null; legacy 1.0.0 giữ numeric constraints. Các artifact/grading khác vẫn 1.0.0; wire BTC không đổi.

Nguồn/nhãn ở [ma trận](schema-contract-matrix.md#2-nguồn-và-quyền-quyết-định). [NHÓM] là thiết kế bổ sung, không sửa công thức BTC. Schema: [contracts.schema.json](contracts.schema.json), $defs OfficialReport / SupplementalReport / Metric / Coverage / ErrorRecord / Comparison / ReleaseDecision.

## 1. Hai lớp báo cáo không nhập làm một

1. **OfficialReport:** JSON do E main xuất nguyên bản. Không thêm judge vào TSR; không sửa mẫu số, không điền số0 cho null. Hash file raw, lưu argv/scorer source hash trong manifest sources và evidence. Bảng E in ra chưa có delta; Comparison adapter bổ sung riêng.
2. **SupplementalReport:** status, checks, coverage và metric nhóm có formula_id/đơn vị/cohort/tử-mẫu/evidence. Liên kết official_report AssetRef, không ghi đè giá trị BTC.

Mọi Metric có metric_id, formula_id, unit, value, numerator, denominator, cohort_ids, evidence_refs, status, reason, currency. Count/latency có thể numerator/denominator=null khi không biểu diễn bằng phân số; vẫn bắt buộc cohort_ids đủ để tính lại. Currency chỉ khác null với tiền, ghi ISO4217, không cộng USD và VND nếu chưa có nguồn tỷ giá ghim trước run. Không thể tính thì value=null và reason; không dùng -1, NaN, Infinity.

File đề xuất: manifest.json, validation.json, official-report.json, supplemental-report.json, comparison.json, table.md, errors.jsonl, release.json. ErrorRecord là mỗi lỗi/ca có expected, observed, evidence, root_cause, remediation, retest_ref và provenance. Bài phân tích ít nhất10 lỗi theo Đ A/F cần lỗi thực; ít hơn10 phải báo thiếu hoặc bổ sung run, không nhân bản fixture để đủ quota.

## 2. Hai trục trạng thái

| Có vi phạm xác nhận? | Evidence | Status.verdict | Status.completeness | Quyết định |
|---|---|---|---|---|
| Không, tất cả check áp dụng đạt | Đủ | PASS | COMPLETE | Có thể xét gate |
| Có | Đủ | FAIL | COMPLETE | Không active |
| Có | Thiếu thêm evidence khác | FAIL | INCOMPLETE | Giữ FAIL; tiếp tục thu phần thiếu |
| Chưa kết luận | Thiếu/lỗi/chưa chốt GT | UNDETERMINED | INCOMPLETE | Không PASS |
| Suite được xác định không áp dụng | N/A | NOT_APPLICABLE | NOT_APPLICABLE | Không đưa vào gate |

“INCOMPLETE” trong flow là trục completeness, không làm mất hard FAIL. Known Agent tạo Handoff Brief thiếu trường có object/evidence → FAIL. Harness không thu được brief → INCOMPLETE; chưa đủ để quy lỗi Agent. Nếu đã chứng minh tool cấm được gọi và thiếu transcript phần sau → FAIL+INCOMPLETE.

Metric status UNDEFINED (ví dụ denominator=0) **không phải** suite NOT_APPLICABLE. N/A chỉ dành cho suite không áp dụng theo manifest/grading; không dùng để che measurement thiếu. Khi một metric bắt buộc UNDEFINED, suite không được PASS trừ protocol BTC đã chốt ngoại lệ. Không “fail Agent” chỉ vì audio BTC chưa phát.

Coverage lưu expected_ids/observed_ids/missing_ids/duplicate_ids/unknown_ids. Expected lấy từ manifest/scenario, không lấy từ output thu được. Không cho duplicate ghi đè trong dictionary rồi mất bằng chứng. Aggregation cả run: bất kỳ vi phạm xác nhận giữ FAIL; đồng thời bất kỳ thiếu bắt buộc giữ INCOMPLETE. Chỉ tất cả suite áp dụng COMPLETE+PASS mới cho overall PASS trên scope đã khai báo.

**Deferred hiện tại:** validate_scenarios.py và audio/segments BTC đầy đủ làm sau theo user. Scope sidecar tham chiếu qua manifest sources ghi reason DEFERRED_BY_USER_2026_10_04; không thêm enum suite/status mới, không gọi BTC requirement là N/A/PASS. Cohort ASR hiện tại chỉ audio team đã đăng ký; missing bên trong cohort vẫn INCOMPLETE. Báo cáo phải hiện deferred và readiness toàn bộ đề chưa đủ; không dùng scope PASS làm release tuyên bố đạt toàn bộ đề.

TimingEvidence 1.1.0: audio_seconds/asr_wall_ms/input_tokens/output_tokens/cost/currency là required nhưng nullable. Missing → null + Issue/metric INCOMPLETE, không số0 giả; trường không áp dụng có reason riêng. Phiên bản1.0.0 giữ kiểu số/currency như trước để đọc artifacts cũ.

## 3. Công thức BTC và giới hạn

Các phần trăm E dùng pct và cách làm tròn trong E; report raw giữ nguyên. Supplemental tính trên raw numerator/denominator, làm tròn chỉ lúc hiển thị.

| Chỉ số / nguồn E | Tử số / mẫu số, cohort | Null/thiếu & kiểm bổ sung |
|---|---|---|
| RQR: repeat_question_rate | 100×câu hỏi thừa/tổng câu hỏi **chỉ call có must_not_ask**; open về slot cấm hoặc confirm lần2+ cùng slot trong call | Không câu hỏi → null; extractor bỏ sót câu hỏi không biến thành improvement |
| CCR: context_carryover_rate | 100×số slot required xuất hiện trong facts_used hoặc key args / tổng len(must_carry_over) | Scorer không chứng minh đúng value/profile/nguồn; fact_value và memory checks riêng |
| TSR: task_success_rate/check_call | 100×scenario có mọi call có success_if đạt / scenario có ít nhất1 success_if truthy | Thiếu rows có thể vẫn pass điều kiện phủ định; coverage chặn supplemental PASS. Ca không success_if không tự bổ sung vào denominator BTC |
| TSR hard | E lấy danh sách hard_case truthy rồi trừ hard_fail | Hard không có success_if vẫn có thể được coi đạt; báo coverage và cảnh báo, không sửa E |
| HR: hallucination_rate | 100×claim sai / claim được E đối chiếu field có GT; price_promo_only là nhóm field E chọn | Claim ngoài GT không tự là hallucination và không được chứng minh đúng; missing_GT supplemental INCOMPLETE |
| Latency: latency | p50/p95 của mẫu E thực nhận, đơn vị ms; giữ thuật toán percentile E | E không tự bỏ3warm-up (B09), không tự bù timestamp thiếu |
| WER/CER: wer_cer | 100×tổng edit distance token/ký tự / tổng token/ký tự GT trên dialogues có hypothesis | CER bỏ khoảng trắng; không clamp100 vì insertion có thể vượt. Hypothesis thiếu bị E skip, coverage phải báo |
| Entity accuracy: wer_cer | 100×entity GT exact-match qua str(hyp)/str(GT) / số entity GT trên dialogue có hypothesis | Hyp thiếu entity được tính sai; hyp thiếu cả dialogue bị skip, cần coverage |
| Diarization turn accuracy: wer_cer | 100×segment GT có hyp chứa midpoint đúng speaker / số segment GT được xử lý | Thiếu turns/segments bị bỏ, phải báo coverage; đây không phải DER |
| RAG recall@3/@5: rag_eval | 100×qid có ≥1 relevant chunk trong topK / qid có relevance và có result | Đây là hit-rate theo câu như E đặt tên; missing qid bị skip denominator |
| RAG multi_hop_full_recall@K | 100×câu multi_hop thu đủ relevant / multi_hop có relevance và result | Không tự coi ít chunk là version fail; answer/version cần check riêng |
| RAG abstain unanswerable/restricted | 100×câu đúng type có abstained=true / tất cả câu GT type đó | Missing result mặc định không abstain trong E; coverage riêng |
| RAG false_abstain | 100×câu answerable abstained=true / toàn bộ câu answerable | Không dùng tỷ lệ thấp để che missing results |
| Avg turns/call | Số trace rows / số call thực có rows theo E | Báo số call planned/observed; duplicate rows không được hợp thức hóa |
| Calls-to-close | Theo E calls_to_close; báo n_closed,n_scenarios | Optional theo GD Team8 Q3; không thay turns/scenario |

Ngưỡng bắt buộc Đ A/C.4: RQR giảm tương đối≥40%, TSR≥70%, HR giá/KM≤5%. Baseline RQR=0 → giảm tương đối null/UNDEFINED; E cờ meets=false, **không** coi full=0 là giảm100%. Báo baseline/system tuyệt đối và chờ cách chấm ngoại lệ; release evidence chưa đủ cho tiêu chí giảm.

## 4. Registry công thức bổ sung [NHÓM]

formula_id là tên dưới đây. Chưa có runtime formula engine tổng quát; P4 nối tool-accuracy.v2/fact-value.v1 và verified close trong Metric/report. Các formula khác phải triển khai ở phase tương ứng và chạy A/S. Checker tái tính ratio.v1, percent.v1, tool-accuracy.v2 và cost-call.v1 trên fixtures, không chứng minh matcher, runtime tool success, cost collection hoặc toàn bộ metric đã implement. P0 đã có matcher context-level và cost arithmetic trong [metrics.py](../eval_harness/metrics.py), có regression tests riêng; P4 đã nối matcher với pinned labels/typed ToolEvent và Metric/evidence; cost vẫn arithmetic P0, runtime cost collection và A14 end-to-end còn pending. tool-accuracy.v1 chỉ dành đọc report lịch sử; run mới không dùng.

| formula_id | Công thức / đơn vị | Cohort và dữ liệu thiếu |
|---|---|---|
| ratio.v1 / percent.v1 | n/d; hoặc100n/d | d=0→UNDEFINED, thiếu evidence→INCOMPLETE |
| rqr-reduction.v1 | 100×(RQR_base−RQR_full)/RQR_base, percent | cùng frozen/hash/config khác memory; baseline0/null→UNDEFINED |
| delta.v1 | system−baseline | rate dùng percentage_points, latency ms; một bên thiếu→null |
| turns-call.v1 | N agent turns / N planned calls hoàn tất | turns_per_call; phải đủ trace. Không dùng observed denominator để che call mất |
| turns-scenario.v1 | N agent turns / N planned scenarios hoàn tất | turns_per_scenario; không gọi bằng tên turns/call |
| tokens-call.v1 | Tổng input/output tokens Agent runtime / số call hoàn tất | unit=count trong schema hiện tại; missing/reconciliation chưa đủ→INCOMPLETE, completed0→UNDEFINED; không bỏ tokens của failed calls |
| cost-call.v1 | Tổng runtime cost LLM+ASR+TTS+tool của cohort (kể cả call lỗi) / số call hoàn tất | currency_per_call; completed=lifecycle kết thúc+after-call barrier, không phải TSR PASS. Báo attempted/completed/failed; d=0→UNDEFINED. Cùng currency/giá/usage ghim; thiếu usage/price→INCOMPLETE; judge/simulator riêng |
| asr-time.v1 | (tổng asr_wall_ms/1000)/(tổng audio_seconds/60) | seconds_per_audio_minute, duration0→UNDEFINED; warm-up ASR khai báo cohort riêng |
| latency-p95.v1 | percentile theo E, trên timestamp derived hợp lệ **sau3warm-up** | ms; báo raw/effective count; thiếu mốc không thay0 |
| tool-accuracy.v2 | 100×TP/(TP+FP+FN), invocation name+expected args; result success không nằm trong TP | percent; matching1–1 theo thứ tự/điều kiện; wrong args→FP và expected chưa đáp ứng→FN; optional allowed không FN, unauthorized extra FP. Invocation đúng/result lỗi vẫn TP; execution failure riêng. d=0→UNDEFINED, không100%; precision/recall báo riêng |
| fact-value.v1 | 100×required fact-use đúng value/profile/context / số required fact-use | percent; GT disputed→INCOMPLETE, không dùng CCR thay thế |
| answer-accuracy.v1 / version-accuracy.v1 | 100×PASS / số qid áp dụng có GT chốt | percent; missing result/judge/GT→INCOMPLETE, báo disputed count, không rút cohort âm thầm |
| agreement.v1 | 100×cặp nhãn giống / tất cả cặp có cả2nhãn | percent; sampling frame+seed; thiếu20cặp theo J chưa đạt protocol |
| kappa.v1 | (Po−Pe)/(1−Pe); Pe từ marginal PASS/FAIL | ratio; Pe=1 hoặcN=0→UNDEFINED; không gán1 |
| simulator-mean.v1 | sum(TSR_seed)/3 | percent; đủ3seed trên cùng scenarios; thiếu1→INCOMPLETE |
| simulator-std.v1 | sqrt(sum((x−mean)^2)/3) | percentage_points; population std nhóm chọn, không tự nhận BTC đã chốt |
| simulator-range.v1 | max(TSR_seed)−min(TSR_seed) | percentage_points; ≤10pp là gate bảo thủ nhóm (B12) |

Tool raw results được kiểm theo MO/tool thực: HTTP200/không exception không tự là success; error hoặc không có bằng chứng side effect đã xảy ra → thất bại có bằng chứng hoặc incomplete tương ứng. Expected args subset giữ semantics E (null ignored) chỉ trong report BTC; supplemental labels không dùng null để che điều kiện chưa xác định.

Timestamp TTFT=first_token−request; total=completed−request; voice TTFA=first_audio−VAD_end; CallBrief=ready−identified bao gồm refresh theo L5. Backend monotonic duration nên dùng để chống clock drift; ISO timestamps dùng đối chiếu trật tự. Mốc âm/inconsistent → measurement invalid. Quality vẫn chấm3warm-up. Theo L: ≥100 lượt raw, bỏ3 để báo effective; công bố cả2count để B09 không bị giấu. M1 TTFTp95≤3000ms, totalp95≤8000ms, Brief≤5000ms; M2 TTFAp95≤2500ms, Brief≤3000ms, ≥2phiên đồng thời theo DC/L.

Chi phí harness judge/extractor/simulator cần tách khỏi chi phí cuộc gọi Agent; metric_id có namespace agent./harness.; không gộp rồi so Agent baseline/full lệch phạm vi. FX hoặc đơn giá ngoài nguồn BTC là cấu hình nhóm ghim trước run, không cần cập nhật giá internet trong thiết kế contract.

## 5. So sánh, A.6 và release

Comparison link hai report đã hash và dataset_hash; rows chứa metric_id/baseline/system/delta/delta_kind/unit/status/reason. RQR giảm dùng relative_reduction; các rate khác mặc định system_minus_baseline (pp), không đảo dấu ngầm. Lưu chiều “tốt hơn” trong định nghĩa metric, bảng hiển thị rõ. Table.md chỉ render từ Comparison, không là nguồn số độc lập.

A.6 mở rộng có Baseline | System | Delta | Coverage | Trạng thái. Các hàng tối thiểu: RQR,CCR,TSR,TSR hard,HR price/promo,turns/call,turns/scenario,latency raw/effective,cost/call; ASR/RAG/M2 theo applicability. Mean/std/range simulator ở bảng riêng theo seed.

ReleaseDecision chỉ active khi:
- Scope/claim của release được khai báo rõ; deferred BTC audio hiện tại không được gọi là đủ yêu cầu đề. Decision tuyên bố nghiệm thu toàn bộ đề phải hold cho tới khi mở lại và đo đủ requirement deferred.
- ApprovalRecord quyết định approve và đúng content hash candidate.
- Hash content thực tế trùng approved/evaluated/manifest; không chỉ ba chuỗi bằng nhau.
- Các suite áp dụng được khai báo đủ; không dùng suite_results=[] làm mọi điều kiện đều đúng.
- Bắt buộc BTC đạt theo protocol đã chốt, supplemental hard checks không fail, coverage đầy đủ, disputes ảnh hưởng đã được giải quyết.
- So phiên bản không regression theo gate nhóm ghim trước run; rollback có previous_version.

Không áp công thức simulator/judge/RAG của M2 để chặn M1 không đăng ký suite đó. M2 đăng ký nhưng thiếu kết quả không được đổi applicable=false sau run. Suite NOT_APPLICABLE phải có reason từ manifest trước run.

## 6. Đầu ra lỗi và thiếu

ValidationReport ghi Issue classification: schema_error / missing_evidence / agent_violation / dispute / infra_error. errors.jsonl phục vụ phân tích chứ không tự thành Growth. Evidence gốc không xóa dù schema sai; đặt ngoài scorer input, kèm invalid-object reference, giữ kế hoạch mẫu số trong coverage. Redaction PII có hash trước/sau chỉ khi được phép giữ raw trong nơi hạn chế; gói bàn giao không chép PII production.

Không retry Agent/tool để chọn lần tốt nhất. Judge repaired output lưu cả attempts và raw lỗi trong error artifact. Không publish khi kết quả đo chưa hoàn tất. Tất cả con số trong examples/fixtures là giả lập và được báo như vậy.

## 7. Implementation checkpoint07/10/2026

P6 report/benchmark đã có; optional billing ledger/casebook review importers theo [protocol](../p6-input-evidence.md). Đây là staging sidecars, không đổi contracts.schema.json hoặc wire BTC. Ledger kiểm exact hook/binding coverage kể cả failed requests, giá/units/currency/digests; không tự xác minh provider authenticity. Casebook bind source error và distinct retest raw/trace/run, không dùng fixture đủ quota. RQR relative reduction dùng exact Fraction từ counters để không đánh trượt đúng40% vì float. Source validation cũ không bị sửa/xóa khi nhập evidence mới.

P7 compare-rounds chỉ diagnostic Comparison/readiness hold, chưa là release authority. Errors R0 cần được liên kết với retest R1 ở package; không yêu cầu R1 sạch tự tạo lỗi để đủ casebook. Xem [README](../README.md) để phân biệt code evaluator với đường tích hợp product chưa hoàn tất.
