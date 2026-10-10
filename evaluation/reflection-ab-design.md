# Reflection và A/B — bổ sung vào Evaluation

Implementation đọc [README](README.md) và [plan](evaluation-implementation-plan.md) trước. Reflection/A/B là cơ chế sản phẩm tùy chọn; scope evaluator chỉ nhận/kiểm artifacts khi runtime dùng, không tự implement lesson generator hay live experiment.

Ngày 04/10/2026. **Chỉ thiết kế, chưa build/chạy Agent.** Reflection đã có khung ở D3; A/B được bổ sung như lựa chọn M2 của nhóm, không phải một suite BTC bắt buộc mới. Dùng chung candidate/review/evaluation/version theo Ponytail, không tạo hệ thống duyệt thứ hai.

<a id="reflection"></a>

## 1. Reflection: sau mỗi call có record, không phải mỗi call sửa memory

**Đầu vào:** trace hoàn chỉnh sau ô8, tool/outcome, working context đã xác minh, QA ô10 và phiên bản policy. Thiếu evidence → record pending, không tự viết bài học như sự thật.

```text
8. After-call → 10. QA + Reflection record
                        ↓
           lesson / no-change / pending
                        ↓
                 Source Gate
       deny → report-only; pending → review
                        ↓ allow
               11. Evidence Pool
                        ↓
      12. Đủ evidence phù hợp? → chưa: chờ
                        ↓ có
               13. Playbook draft
                        ↓
          14. Policy + người duyệt
                        ↓
             15. Evaluation Gate
                        ↓ PASS
               16. Active playbook
```

QA được làm cho mọi call kể cả nguồn test. Reflection draft cũng có thể lưu để phân tích nhưng chỉ nguồn allow mới đưa sang pool học; không tự cập nhật prompt trong một run đo. Cổng nguồn kiểm trước khi sử dụng draft để học, không ngăn memory nghiệp vụ call1→call2 đang được đo.

### Record có cấu trúc [NHÓM]

| Trường | Cách dùng |
|---|---|
| `reflection_id`, `run_id`, `scenario_id`, `call_id`, `source_refs` | Định danh và đoạn evidence; retry cùng call không tạo support mới |
| `decision` | `lesson`, `no_change`, `pending`; kèm reason |
| `situation`, `objection_type`, `persona_tag` | Tình huống có căn cứ; không đoán đặc điểm riêng khách |
| `what_worked`, `what_failed` | Điều quan sát được, gắn turn/tool refs; không suy “chốt được vì câu này” |
| `lesson`, `suggested_action`, `applicability`, `exclusions` | Draft hướng dẫn dùng chung; `lesson=null` khi no_change/pending |
| `evidence_refs`, `policy_refs`, `uncertainty` | Căn cứ, thời điểm hiệu lực, điều chưa xác minh |
| `source_decision_ref`, `validation_status` | Quyền học và schema/policy/PII/grounding checks |

**Phân biệt ba kho:** (1) Reflection record nháp là evidence, không được Advisor retrieve; (2) fact riêng khách được MemoryAgent kiểm và ghi ledger theo pipeline memory, không qua lesson chung; (3) bài học dùng chung chỉ vào playbook/knowledge **active sau14–15**. “Ghi bộ nhớ” ở đây là ghi tri thức đã duyệt, không nhét bài học nháp vào memory khách hoặc sửa trọng số model.

Model viết draft phải trả JSON theo contract nhóm, dữ liệu trace chỉ là input không phải instruction. Validate schema, evidence refs tồn tại, PII, policy đúng ngày và claim được hỗ trợ. Output lỗi → pending; không thay bằng lesson mặc định. QA người hoặc judge khi áp dụng kiểm căn cứ, không chỉ hình thức JSON.

### Pool, hợp nhất và đề xuất

- Nhóm theo điều kiện tương đương; giữ cả evidence ủng hộ và phản bác, một call/replay không nhân bằng chứng.
- Dùng ngưỡng3 call độc lập của D3 để đưa lesson lặp đi lặp lại đi review; đó là thiết kế nhóm, không phải chứng minh thống kê hay bắt buộc mọi sửa lỗi phải chờ3.
- Lỗi PII/policy nghiêm trọng → incident/review ngay, không chờ đủ support; hành động an toàn tạm thời không tự biến một draft thành playbook active.
- Một thay đổi là một entry versioned; không để model tự viết lại toàn bộ playbook. Candidate gồm source refs, applicability, nội dung thay đổi và Growth tests có GT độc lập.
- 14 duyệt nội dung/hash; 15 kiểm candidate vs active, harmful-regression và suite áp dụng; 16 active/rollback. Lesson không đủ bằng chứng → pending/no-change, không bịa một cải tiến để đủ R2.

**Nghiệm thu:** call thường → no-change; thiếu trace → pending; bài học từ Frozen → report-only theo D1; advice hứa KM sai → reject; PII → không vào playbook; sửa candidate sau PASS → đo/duyệt lại; policy đổi → vô hiệu entry liên quan, review version mới.

<a id="ab"></a>

## 2. A/B kịch bản xử lý phản đối — thiết kế M2 tùy chọn

Đây là **so sánh hai chiến thuật**, không phải full/baseline memory, cũng không phải Exemplar OFF/ON. Bản đầu chạy **offline** với mock/simulator, không thử trên khách thật hay tạo hai đơn thật. Production experiment cần quyết định và quyền vận hành riêng.

Ví dụ: phản đối “giá cao”: A giải thích lợi ích đã có nguồn; B nêu phần vượt budget và đề nghị tra lựa chọn khác. Cả hai không được tự hứa giảm giá. Không tạo response cố định trái policy; chỉ khác instruction xử lý phản đối.

```text
Pool / người đề xuất → experiment draft A và B
                              ↓
                14. Duyệt cả hai + protocol
                              ↓
        15. Hai nhánh độc lập trên cùng scenario/seed
                    A            B
                    ↓            ↓
               QA + tool + outcome + metrics
                              ↓
           an toàn? đủ coverage? đủ bằng chứng?
      Không → pending/reject; có → đề xuất bản tốt hơn
                              ↓
             review bản được chọn + Growth tests
                              ↓
          15. Gate toàn bộ candidate được chọn
                              ↓ PASS
                     16. Active / rollback
```

**Không vòng lặp đo vô hạn:** vòng15 đầu là experiment, vòng15 sau là release gate trên candidate đã chọn. Nếu cùng snapshot/report đã đo đủ suite và được14 xác nhận đúng hash thì tái sử dụng evidence, không bắt buộc chạy lại identical run. Nếu chỉnh bản thắng, đổi cohort hoặc thiếu suite thì phải đo phần liên quan lại. Experiment report không tự cấp quyền publish.

### Protocol phải chốt trước run

| Thành phần | Quy tắc [NHÓM] |
|---|---|
| Đơn vị | Scenario/chuỗi nhiều call của một khách, không đổi A↔B giữa phiên của cùng chuỗi |
| Eligible cohort | Khai báo trước: loại phản đối, nguồn có quyền dùng, khả năng mua; không chọn case sau khi thấy kết quả |
| Một biến khác | Instruction xử lý phản đối A/B; model, tool/policy, memory mode, FAQ/playbook/exemplar ngoài phần đó giữ nguyên |
| State | Hai namespace và seed nghiệp vụ riêng nhưng tương đương, đồng hồ ảo/ngày gọi như nhau; không dùng chung order/memory/job state |
| Nguồn test | Development/Growth để chọn cách; Frozen chỉ đo/report theo D1, dùng để chọn thì khai báo đã tuning, không gọi holdout độc lập |
| Khách mô phỏng | Cùng persona và seed, nhưng mỗi nhánh có lịch sử riêng. Nhận lời Agent của nhánh mình, không dùng transcript nhánh khác |
| Simulator BTC | Ba seed; giới hạn12 lượt chỉ simulator; fixed-turn không bị cắt12 và không trở thành customer simulator |
| Thực thi | Có thể song song nếu tài nguyên cho phép; không bắt buộc concurrency để phép so hợp lệ. Cache chứa variant/prompt/context hash |
| Fixed-turn | Hữu ích đo safety/task trên input như nhau; khách viết sẵn có thể đã quyết định mua nên không chứng minh uplift conversion thực tế |
| Stopping rule | Chốt cohort/seed trước; chạy hết, không dừng ngay khi B dẫn; số mẫu/target uplift/ngưỡng bằng chứng ghim trong protocol |

Không lộ `success_if`, persona hidden hoặc đáp án vào prompt chiến thuật. Agent vẫn chỉ nhận context được phép. “Chạy song song” không có nghĩa hai biến thể cùng tư vấn một khách thật.

### Cách tính và chọn bản

**Primary supplemental metric:** tỷ lệ chốt = số scenario/chuỗi eligible có ≥1 **đơn mới** `order.create` thực sự thành công, không vi phạm an toàn / tổng số scenario/chuỗi eligible được phân cho nhánh ×100%. Một chuỗi nhiều đơn vẫn tính1; đơn seed có sẵn không tính chốt mới. Báo thêm raw order success và unsafe-order count để không che việc chốt bằng hứa sai. Đây **không phải TSR BTC** và không thay mẫu số official.

Chạy3 seed: tính per-seed trên cùng scenario IDs, báo mean/std/range của tỷ lệ và ΔB−A; seed lặp không biến thành3 khách độc lập. Với paired offline, lưu mỗi cặp: cả hai chốt / chỉ A / chỉ B / cả hai không chốt; thiếu một phía là cặp incomplete, không silently loại khỏi cohort.

Lỗi kỹ thuật/thiếu evidence giữ trong tổng assigned, báo coverage và khoảng tỷ lệ có thể đạt (`verified_wins/N` đến `(verified_wins+unresolved)/N`); chưa đủ evidence không quyết định winner. Policy violation là FAIL đã xác minh, không biến thành unresolved.

Thứ tự quyết định: **safety → completeness → tác động → chi phí/latency → review**. Không có chính sách BTC về significance/conversion threshold cho experiment này: nhóm phải ghim effect tối thiểu và phương pháp paired uncertainty trước run khi muốn tuyên bố thắng thống kê. Chưa có protocol đó hoặc ít mẫu → chỉ “B tốt hơn trên tập quan sát”, không “B tốt hơn nói chung”, không auto-active. Default giữ active nếu hòa/chưa rõ; reviewer không được biến thiếu evidence release bắt buộc thành PASS.

Bất kỳ nhánh hứa sai/PII nghiêm trọng → loại khỏi lựa chọn release dù conversion cao. Winner cũng phải qua các suite15 theo mức đang chạy, Growth mục tiêu và non-regression; cost tăng phải báo. Release snapshot chứa variant instruction hash, bank/playbook version và protocol/report refs. Rollback đổi bundle đã duyệt, không tự sửa prompt giữa experiment.

**Nghiệm thu:** A/B dùng chung memory → lỗi isolation; B tạo đơn tool error → không chốt; cùng khách ba call → mẫu số1; order seed → không tính; B dẫn ở seed1 nhưng giảm seed khác → chưa kết luận chung; thiếu run B → INCOMPLETE; cải thiện nhờ cả đổi model và strategy → không quy tác động strategy; Frozen dùng chọn winner → đánh dấu tuning; winner sửa sau PASS → report cũ không đủ.

## 3. Hợp đồng còn phải bổ sung trước build

| Artifact thiết kế | Producer → consumer | Nội dung chính |
|---|---|---|
| ReflectionRecord | QA/Reflection → validator/pool | Record per-call, lesson/no-change/pending, refs và uncertainty |
| LessonCandidate | Consolidator → review/gate | Entry playbook versioned, applicability, sources, Growth refs |
| ExperimentProtocol | Người thiết kế → runner/evaluator | A/B hash, cohort, seed, state isolation, metric và stopping/decision rules |
| VariantResult | Runner/extractor → evaluator | Scenario/seed/variant, new-order evidence, verdict/coverage, timing/cost |
| ExperimentComparison | Evaluator → review/gate | Paired results, rate/delta, unresolved, harm, conclusion scope |

Đây là đặc tả trường và hành vi, **chưa thêm JSON Schema/fixture**. Dùng Candidate kind `playbook`/`prompt` khi đúng nghĩa, SourceDecision/ApprovalRecord/ReleaseDecision hiện có; record và experiment artifact mới cần schema versioned riêng. Không dùng raw verdict judge làm record lỗi Reflection hoặc experiment.

## 4. Kết nối và nguồn

- [Evaluation D3/D5–D7 và D9–D10](evaluation-flow.md#improvement): Source Gate, record mọi call, pool, review và gate theo level.
- [Flow lịch sử §18.4–18.5](temp-repo-for-agent/docs/flow.md): playbook có cấu trúc, entry versioned và ablation; repo từng chọn Reflection thay A/B vì hạn chế mẫu. Thiết kế này bổ sung A/B offline nhưng giữ hạn chế đó, không khẳng định có lưu lượng/statistical power.
- [BTC simulator spec](BTC-Data-Vong1-TEAMS/simulator/customer_simulator_spec.md) và [mentor Team8](BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md): simulator chuẩn,3 seed; metric fixed-turn vẫn riêng.
- Các luật protocol và supplemental conversion ở đây là **[NHÓM]**, không gọi là công thức/threshold BTC. Không fine-tune.
