# Evaluation — M1 chính, M2 mở rộng

Bản thiết kế cập nhật ngày 01/10/2026, xử lý F01–F17 của [bản audit](can_sua.md). Giữ các ô **6a, 6b, 6c, 8, 10–16** của flow gốc. Đây là thiết kế và hợp đồng nghiệm thu, **không phải tuyên bố runner đã triển khai hoặc Agent đã chạy đạt**.

Mở bằng **Cmd + Shift + V** trong VS Code. Các sơ đồ là PNG, xem offline không cần tiện ích Mermaid; bấm ảnh để mở kích thước đầy đủ. Khi chuyển tài liệu, mang theo thư mục ảnh đi kèm.

## Mục lục

1. [Toàn cảnh và cách đọc](#overview)
2. [Evaluation M1: dữ liệu → chạy → kiểm chứng → báo cáo](#m1)
3. [M2: judge, RAG, diarization, simulator, tool và voice](#m2)
4. [Cải tiến, Source Gate, Growth và phát hành](#improvement)
5. [Phụ lục: rubric, nguồn, tranh chấp, nghiệm thu](#appendix)

## Quy ước dùng xuyên suốt

| Nhãn | Ý nghĩa |
|---|---|
| **[ĐỀ/BTC]** | Yêu cầu từ PDF và tài liệu điều chỉnh BTC; có nguồn ở cuối mục. |
| **[SCORER]** | Hành vi thực của reference_eval.py; đôi khi hẹp hơn ý nghĩa yêu cầu. |
| **[NHÓM]** | Cách tổ chức hoặc phép kiểm tra bổ sung do nhóm chọn; không tự gọi là chuẩn BTC. |
| **CHỜ BTC** | Hai nguồn chưa thống nhất hoặc tài sản chưa được phát; không tự chọn đáp án. |

**Ô 10** chấm từng cuộc gọi để ghi nhận chất lượng và tìm tín hiệu cải tiến. **Ô 15** đo một phiên bản hệ thống trên bộ test và quyết định có đủ bằng chứng phát hành hay không. Hai ô có thể dùng chung bộ chấm, nhưng ô 10 không có quyền tự cập nhật KB active.

Trong các bảng, Đ/DC/GD/E/J/L/SIM/SC/TR/HB/ASR/RAG là ký hiệu nguồn có liên kết ở [E2](#sources). Số liệu inventory là snapshot **46 file BTC thực nhận**, không phải số liệu hệ thống nhóm.

<a id="overview"></a>

# A. Toàn cảnh

## A1. Hai nhánh cải tiến hội tụ trước khi active

**Mục đích:** nhìn được phần QA/evaluation nối vào flow gốc mà không trộn với đường xử lý cuộc gọi 1–7.

**Đầu vào:** evidence sau cuộc gọi ở ô 8; câu trả lời có nguồn của consultant ở ô 6a. Cổng nguồn được gọi ở cả hai nhánh; điều kiện chi tiết xem D1.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart RL
    A["8. After-call"] --> B["10. QA / Reflection"]
    B --> S{"Source Gate"}
    S -->|"Được học"| C["11. Evidence Pool"]
    C --> D{"12. Đủ evidence?"}
    D -->|"Có"| E["13. Playbook draft"]
    D -.->|"Chờ thêm"| C
    E --> R["14. Policy + người duyệt"]
    F["6a. Consultant"] --> G{"Source Gate"}
    G -->|"Được học"| H["6b. FAQ draft"]
    H --> I["6c. Candidate + test"]
    I --> R
    S -->|"Chặn / chưa rõ"| X["Chỉ báo cáo / review"]
    G -->|"Chặn / chưa rõ"| X
    R --> V["15. Evaluation Gate"]
    V -->|"PASS"| K["16. KB active + rollback"]
    V -->|"FAIL / INCOMPLETE"| Y["Giữ active; sửa candidate"]
    R -->|"Chưa duyệt"| Y
    D -->|"Lỗi nghiêm trọng"| R
```


**Đầu ra:** FAQ/playbook có nguồn, được duyệt và kiểm chứng trước khi active; hoặc candidate bị giữ lại kèm lý do. Nhánh lỗi nghiêm trọng đi review sớm, không bỏ qua ô 15. Flow chi tiết cho 6a–6c, 8–13, 14 và 16 nằm ở phần D.

**Thiếu/lỗi:** dữ liệu test, nguồn chưa rõ hoặc chưa được phép học vẫn được QA và báo lỗi; không tự đổ vào Evidence Pool. Consultant trả lời không tự biến thành ground truth. [Đ C.5 tr.7; NHÓM]

## A2. Bên trong ô 15: các suite độc lập

**Đầu vào:** phiên bản cần đo, level M1/M2, bộ dữ liệu đã chốt, cấu hình và hợp đồng chấm. R0 không cần có candidate/active trước đó.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Phiên bản + level + manifest"] --> B["Chốt bộ test và suite áp dụng"]
    B --> C["M1: fixed-turn full / baseline"]
    B --> D["M1: ASR + latency + cost"]
    B --> M{"Có phần M2?"}
    M -->|"Có"| E["Judge / RAG / diarization<br/>Simulator / tool / voice"]
    M -->|"Không"| N["M2: NOT_APPLICABLE"]
    C --> F["Validate trace + coverage"]
    F -->|"Hợp lệ"| G["Scorer BTC<br/>+ kiểm tra bổ sung"]
    F -->|"Thiếu / sai"| I["INCOMPLETE + chẩn đoán"]
    D --> H["Tổng hợp evidence từng suite"]
    E --> H
    G --> H
    I --> H
    N --> H
    H --> R{"Đủ bằng chứng áp dụng?"}
    R -->|"Chưa"| Q["Giữ candidate; báo thiếu"]
    R -->|"Đủ"| T["Bảng chỉ số + lỗi<br/>So phiên bản / release"]
```


Suite không phải lựa chọn loại trừ nhau. Frozen và Growth dùng cùng cơ chế nhưng **chạy, gắn nhãn và báo riêng**. Hidden chỉ được chạy khi BTC cấp/ủy quyền, không là điều kiện phải có sẵn cho release nội bộ.

| Suite | M1 | M2 | Nếu thiếu |
|---|---|---|---|
| Fixed-turn, full/baseline, 5 nhóm metric nền | Bắt buộc | Kế thừa | INCOMPLETE; không công bố đủ evaluation |
| ASR local, BTC khi phát + ≥ 20 file nhóm | Bắt buộc | Kế thừa, thêm diarization | Phân biệt phần đã đo và phần chưa nhận |
| Latency, Call Brief, chi phí | Bắt buộc theo đề/giải đáp | Thêm voice và đồng thời | Thiếu số đo không tự xem là đạt |
| Judge theo rubric, đối chiếu người | Dùng nếu mục tiêu lời thoại cần chấm | Bắt buộc | M1 assertion-only có thể NOT_APPLICABLE; judge đã chọn thì thiếu là INCOMPLETE |
| RAG, diarization, simulator, Tool-Call Accuracy | NOT_APPLICABLE nếu không chọn | Bắt buộc | Không đóng nhãn NOT_APPLICABLE để né M2 |
| Vòng cải tiến | R0/R1 | R0/R1/R2 trở lên | Chưa đủ số vòng thì chưa chứng minh đủ mức |
| Calls-to-Close | Không bắt buộc | Tùy chọn theo GD | Không chặn release chỉ vì không báo |

**Bốn trạng thái [NHÓM]:** PASS = đủ bằng chứng và đạt hợp đồng; FAIL = có bằng chứng vi phạm; INCOMPLETE = thiếu/lỗi/tranh chấp ảnh hưởng kết luận; NOT_APPLICABLE = không thuộc hợp đồng đã chốt. Trạng thái này ở report bổ sung, không đổi schema/điểm official. Một hard FAIL đã biết vẫn giữ FAIL dù phần judge còn thiếu; đồng thời coverage của suite vẫn INCOMPLETE, không che lỗi bằng một nhãn tổng duy nhất.

**Đầu ra:** report BTC nguyên bản + report bổ sung + coverage + bảng so sánh. Điểm thô từ scorer có thể dùng chẩn đoán run thiếu, nhưng không là chứng nhận run hoàn tất. [Đ C.4–C.5; DC §1–2,7–12; GD Team8 Q3]

<a id="m1"></a>

# B. Evaluation M1

## B1. Dữ liệu, ground truth và cấu hình cố định

**Mục đích:** chốt “đo cái gì, bằng nguồn nào” trước khi chạy.

| Tập | Thực nhận / yêu cầu | Dùng để làm gì |
|---|---|---|
| Public BTC | 7 scenario,13 call,39 lượt;4 thường+3 hard theo file | Tương thích định dạng, không thay bộ nhóm |
| Team Frozen | [ĐỀ] M1 ≥ 20 scenario đa phiên +≥ 5 hard; M2 ≥ 40 | So baseline/full và các vòng trên cùng version |
| Team Growth | Nhóm tự tạo, review và version | Chống tái phạm; không tự nhập Frozen |
| Hidden BTC | Tài liệu mô tả41 case/19 hard; chưa nhận | Chấm chéo, không dùng làm nguồn học tự động |
| ASR BTC | 4 GT D01–D04,34 lượt; chưa có audio/segments | Chưa đo được ASR BTC chỉ từ GT |
| ASR nhóm | ≥ 20 file eval, audio + transcript + entity chuẩn | WER/CER và tiền/SĐT |
| RAG M2 | 60 QA, corpus14 file/99 chunk | Không thay dataset phát triển C.1; xem C3 |
| Nền nghiệp vụ | 40 parent+96 variant;13 promo;50 CRM seed | Ground truth theo ngày/điều kiện |

Cụm “20 +5” chưa rõ hard tính trong hay ngoài tổng. [NHÓM] Kế hoạch an toàn:20 scenario đa phiên thường +5 hard riêng; báo cả ba số, **không gọi25 là mức BTC đã xác nhận**. Không ép public SAMPLE-07 chỉ có một call thành đa phiên. Dataset phát triển C.1 vẫn phải tự sinh; Frozen/public không thay định mức hội thoại/audio đó. [Đ C.1/C.4; DC §2; R PUBLIC/Giữ lại]

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Inventory file + version nguồn"] --> B["Validate scenario và coverage"]
    B --> C["Đối chiếu GT với policy / tool / ngày"]
    C --> D{"Nguồn thống nhất?"}
    D -->|"Không"| E["Ghi tranh chấp; xin BTC<br/>Không sửa raw / bỏ case"]
    D -->|"Có"| F["Chốt dataset + grading contract"]
    E --> G["Giữ run chẩn đoán<br/>Không kết luận phần tranh chấp"]
    F --> H["Ghim model / prompt / tools / KB"]
    H --> I["Manifest trước run"]
    B -->|"Schema sai / thiếu"| J["Sửa input nhóm<br/>BTC raw giữ nguyên"]
```


**Đầu vào/ra:** scenario, policy/catalog/mock version → manifest bất biến cho lần đo. Manifest ghi run_id, mục đích/split/level, danh sách scenario-call-turn dự kiến, dataset/GT hash, model/parameters, prompt/tool/KB version, seed, hardware/API, scorer/extractor/judge version, suite áp dụng, rules chấm và tranh chấp mở. Đây là metadata nội bộ, không thêm bắt buộc vào schema BTC.

Coverage matrix liên kết **case_id → level → hard family → call/channel/date → expected checks**. Bao phủ các họ lỗi DC §11: đổi ý/mâu thuẫn, KM hết hạn/điều kiện size, đa kênh, chung SĐT, lịch sử8 tháng/TTL/successor, ASR/teencode, PII/nội bộ,3 phiên/status, AI/xóa dữ liệu, giỏ hàng/budget/COD, đổi sản phẩm, policy cũ, lịch nghỉ, đối thủ, hết hàng. Không tự gán level M1/M2 thay BTC; scenario của nhóm ghi mức kiểm thử rõ ràng.

**Thiếu/lỗi:** không lặng bỏ case khó hoặc sửa nhãn để PASS. Sửa test nhóm sai phải tạo dataset version mới và đo lại các hệ thống cần so trên version ấy. GT chỉ cấp cho bộ chấm/simulator nội bộ, không cấp cho Agent. Điểm tranh chấp xem E3.

## B2. Runner đa phiên, baseline và after-call

**Mục đích:** đo tác dụng của memory trong điều kiện công bằng. **Đầu vào:** manifest + scenario + full/baseline_no_memory.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Tách state run / config / scenario<br/>Nạp seed một lần"] --> B["Call hiện tại:<br/>Tính ngày và chọn input"]
    B --> C{"Cấu hình?"}
    C -->|"Full"| D["Nạp memory phiên trước<br/>Refresh Call Brief"]
    C -->|"Baseline"| E["Không nạp memory phiên trước"]
    D --> F["Chạy lần lượt customer turns"]
    E --> F
    F --> G["Ghi transcript / tools / latency / state"]
    G --> H["8. After-call: chờ memory hoàn tất"]
    H --> Q{"Job hoàn tất?"}
    Q -->|"Không"| X["INCOMPLETE<br/>Ghi lỗi và phần chưa chạy"]
    Q -->|"Có"| R{"Còn call?"}
    R -->|"Có"| B
    R -->|"Không"| Z["Trace + coverage<br/>QA ô 10 không publish KB"]
```


Quy tắc chạy:

- Đọc calls theo thứ tự số; chạy đúng số call của scenario. Fixed-turn không có giới hạn12 lượt của simulator.
- Nếu có customer_turns_asr, đưa **bản này** cho hệ thống và ghi customer_input_mode; không âm thầm dùng customer_turns sạch.
- call_date ưu tiên; nếu thiếu dùng ngày call trước +days_later, call đầu mặc định15/10/2026. Truyền on cho tool xử lý ngày; adapter tôn trọng chữ ký thực của mock, không thêm on mù vào hàm không nhận.
- Seed nghiệp vụ giống nhau ở hai nhánh. Lịch sử hội thoại/brief từ seed_history được nạp theo quyền memory: full dùng; baseline không được đọc lén qua prompt/cache/CRM history. Dữ liệu nghiệp vụ hiện tại cần cho tool vẫn được phép ở cả hai; ghi rõ boundary.
- Cùng model, tham số, prompt nền, tools, catalog/policy, KB và seed snapshot. Chỉ khác nạp memory phiên trước; working memory trong call vẫn có. State/tool side effect tách giữa scenario/config, giữ xuyên các call trong cùng scenario.
- Full bắt đầu cold nếu không có seed_history, không coi mọi call đầu là cold trong ca có lịch sử cũ. Tại nhận diện khách, refresh tồn kho/KM/kênh mới trong thời gian Call Brief.
- Ô8 có thể chạy nền ở production, nhưng evaluation phải chờ memory hoàn tất trước call sau. Memory lỗi/time-out được ghi riêng; không tạo log giả thay lượt chưa chạy.
- Không tự kích hoạt FAQ/playbook trong run. QA/Reflection chỉ ghi artifact theo quyền nguồn; không biến run đo thành online learning.

**Đầu ra:** trace thực + state evidence và execution coverage. Hợp đồng CLI BTC cần triển khai là:
“python run_eval.py --scenarios <dir> --config full --out full.jsonl”, tương tự baseline_no_memory. Đây là hợp đồng thiết kế, không khẳng định lệnh hiện có. [R dòng34–36; SC; Đ A.6 tr.13]

## B3. Validate trace và kiểm tra đủ evidence

**Mục đích:** không để thiếu dữ liệu trở thành điểm tốt. **Đầu vào:** manifest dự kiến và trace từng config.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Manifest dự kiến + trace"] --> B["Validate TR schema và types"]
    B --> C["Kiểm run / config / ID / thứ tự"]
    C --> D["Đối chiếu scenario / call / turn"]
    D --> E["Kiểm evidence có điều kiện"]
    E --> F{"Đủ và hợp lệ?"}
    F -->|"Có"| G["Được chấm và so chính thức"]
    F -->|"Không"| H["INCOMPLETE + danh sách thiếu"]
    H --> I["Report thô chỉ chẩn đoán<br/>Không bỏ case / không tự PASS"]
```


TR quy định trace từng lượt: run/config/scenario/call/turn, text, questions, facts_used, claims, tool_calls và latency theo required/types. Không chỉ kiểm JSON parse được. Kiểm ID lạ, duplicate turn, thiếu config, trộn run, thứ tự và liên kết tool events. Baseline/full có cùng kế hoạch customer turns trong fixed-turn; Agent có thể tạo số tool events khác nhau.

**Evidence có điều kiện:** case có memory_expectation thì memory_writes **bắt buộc** theo mô tả TR; kèm state snapshot đã che PII cho kiểm tra bổ sung. Khi đo Brief cần timestamp/giá trị tương ứng; schema cho phép ttfa null ở chat không có nghĩa được null ttft/total vốn là integer.

Report coverage ghi planned/observed/valid/missing và danh sách ID. Lượt chưa chạy do lỗi không tự biến thành NOT_APPLICABLE. Nếu call kết thúc sớm theo hợp đồng, ghi termination; phần không được chạy vẫn phải được giải trình, không tự cắt mẫu số official. Với simulator, kế hoạch là scenario/call/seed; số lượt thay đổi hợp lệ và có ended_by, không ép bằng fixed-turn.

**Đầu ra:** validation report và quyền dùng report để kết luận. **Thiếu/lỗi:** chặn kết luận hoàn tất, giữ raw trace để điều tra, không sửa/xóa evidence cho khớp. [TR; SC; E load_trace/check_call; NHÓM]

## B4. Extractor, CCR/HR và các kiểm tra bổ sung

**Mục đích:** phân biệt lời Agent thật với nhãn đáp án. **Đầu vào:** transcript có speaker, tool timeline, memory state và nguồn GT.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Lời Agent + tool timeline + state"] --> B["Extractor: questions / facts / claims"]
    B --> C["Audit người: phát hiện bỏ sót / gán sai"]
    B --> D["Scorer BTC giữ nguyên"]
    C --> E["Kiểm bổ sung: value / ngữ cảnh / nguồn"]
    E --> F{"Có nguồn để kết luận?"}
    F -->|"Có"| G["PASS / FAIL có evidence"]
    F -->|"Chưa"| H["Unresolved + coverage"]
    D --> I["Hai report có nhãn riêng"]
    G --> I
    H --> I
```


Extractor dự đoán từ lời Agent/tool thực, **không chép facts_established, must_carry_over hoặc ground_truth_facts thành prediction**. Consultant được gắn speaker riêng; không lấy câu đúng của consultant tính là Agent đúng.

[SCORER] CCR kiểm tên slot trong facts_used hoặc key tool args; HR chỉ xét claim có field tương ứng trong GT. [NHÓM] Kiểm thêm:

- Fact đúng value, đúng khách, đúng thời điểm và phục vụ mục đích lượt nói; nhắc cho có không chứng minh carryover.
- Claim về giá/KM/policy/tồn kho có nguồn và hiệu lực đúng ngày. Thiếu nguồn là unresolved, không mặc định đúng hay bịa.
- Người đối chiếu mẫu ngẫu nhiên20 turn theo yêu cầu BTC và ghi false positive/false negative của questions/claims; nếu dùng metric audit thì công bố cách matching. [R dòng36]
- Coverage: transcript turns đã extract/tổng expected turns; claim đã có kết luận/tổng claim đã extract. Mẫu số0→N/A, không0% hoặc100%; nghi extractor bỏ sót thì coverage claim này chưa đủ chứng minh độ bao phủ thật.

**Đầu ra:** report official và semantic/coverage report tách biệt. Đã phát hiện lỗi extractor ảnh hưởng metric thì đánh dấu kết quả cần đo lại; không thay prediction bằng GT để “sửa điểm”. [Đ A.2/A.4; E CCR/HR; NHÓM]


## B5. Assertion, TSR và handoff/tool success

**Mục đích:** chấm điều kiện nghiệp vụ bằng code trước khi diễn giải chất lượng lời thoại. **Đầu vào:** trace hợp lệ + success_if của scenario.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Trace hợp lệ + success_if"] --> B["Luôn chạy scorer BTC"]
    B --> C["TSR official + TSR hard<br/>Tử số / mẫu số / lỗi"]
    A --> D["Kiểm bổ sung<br/>Handoff schema / tool result"]
    D --> E{"Đủ evidence?"}
    E -->|"Không"| I["INCOMPLETE"]
    E -->|"Có"| F{"Schema / trạng thái đúng?"}
    F -->|"Không"| X["Supplemental FAIL"]
    F -->|"Có"| P["Supplemental PASS"]
    C --> R["Report riêng từng lớp"]
    I --> R
    X --> R
    P --> R
```


[SCORER] Giữ nguyên check_call: tool_called/args_match, also_ordered, total_match_vnd, brief_must_contain, must_say_any, agent_must_say, must_not_call_tools, forbidden_claims, trace_must_not_match, max_agent_questions. Không tự mở rộng điều kiện official bằng phép AND với mọi guardrail/judge.

- Call không có hoặc có success_if rỗng bị scorer bỏ qua. Scenario eligible nếu có ít nhất một call được chấm; mọi call được chấm phải PASS.
- Mẫu số hard của script lấy mọi scenario có hard_case, có thể khác tập hard eligible. Báo cả hai số, không tự thay công thức.
- tool_called:null không tự cấm mọi tool; xem must_not_call_tools. args_match có expected value null được script bỏ qua.
- Negative-only assertion có thể qua khi trace rỗng: B3 phải bắt thiếu evidence trước khi gọi đó là thành công.

[ĐỀ/BTC] expected_outcome=chuyen_may có thể đạt bằng handoff.transfer với brief hợp lệ, không cần tự chốt đơn. [NHÓM] validate toàn bộ HB required/types trước khi xác nhận handoff đúng; ghi result/ticket. order.create/order.update có args đúng nhưng result.error thì official có thể chưa bắt hết: báo thêm **tool/state failure**, không gọi là đơn đã tạo/cập nhật thành công.

**Đầu ra:** official TSR và lỗi có scenario/call; supplemental schema/tool/state report. **Thiếu/lỗi:** tool result thiếu là INCOMPLETE ở phép kiểm bổ sung; hard FAIL không được judge đảo thành PASS. [DC §4,11; HB; E dòng123–186]

## B6. Memory state và guardrail

**Đầu vào:** memory_expectation, memory_writes, state trước/sau, tool/text logs, định danh khách và ngày gọi.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Case + trace + state evidence"] --> B{"Có expectation / rule áp dụng?"}
    B -->|"Không"| N["NOT_APPLICABLE có lý do"]
    B -->|"Có"| C{"Đủ evidence an toàn?"}
    C -->|"Không"| I["INCOMPLETE; yêu cầu bổ sung"]
    C -->|"Có"| D["Kiểm value / supersede / đúng hồ sơ<br/>TTL / delete khi áp dụng"]
    D --> E["Kiểm PII / nội bộ / AI / handoff thừa"]
    E --> F{"Có vi phạm?"}
    F -->|"Có"| X["FAIL + loại lỗi + vị trí"]
    F -->|"Không"| P["PASS cho phạm vi đã kiểm"]
```


[SCORER] memory_checks là sàng lọc chuỗi, bỏ một số key như superseded/must_not_write_to/address_ttl_check/profile_state. Guardrail regex không bao phủ mọi PII/nội dung/tool args; tổng “violations” không nhất thiết là số scenario duy nhất. report official giữ nguyên.

[NHÓM] Các phép kiểm cụ thể:

| Kiểm tra | Bằng chứng cần có | Điều kiện đúng |
|---|---|---|
| Thay đổi fact | Giá trị trước/sau, op và source | Giá trị mới đúng; giá trị cũ được vô hiệu theo hợp đồng |
| Chung SĐT | Customer_id đã xác nhận, hồ sơ được đọc/ghi | Không gộp hai người hoặc ghi nhầm hồ sơ |
| TTL | effective time/expiry + ngày call | Không dùng fact quá hạn làm thông tin hiện tại |
| Xóa dữ liệu | Yêu cầu xóa và state kiểm chứng sau xử lý | Phạm vi dữ liệu phải xóa không còn truy xuất được |
| PII | Text, memory, tool args và đường gửi model ngoài đã mask | Không lộ CCCD/STK/SĐT/địa chỉ theo quy định áp dụng |
| Policy/an toàn | Policy đúng version, câu nói/tool evidence | Không lộ nội bộ, giả là người thật, hứa sai, chuyển máy thừa |

PII phải được che trước khi ghi log/gửi dịch vụ ngoài; không thu thập một bản audit chứa PII thô để chứng minh đã che. Nếu masking làm contract args/ID không thể đối chiếu, dùng mapping nội bộ bảo vệ và ghi rõ hạn chế; không bỏ privacy vì trace mẫu có dữ liệu chưa che.

**Đầu ra:** kiểm tra theo case/rule, expected/observed đã che PII, source và verdict. Không áp tất cả rule M2 vào mọi case M1; nhưng rule đã được scenario/hợp đồng yêu cầu thì không được né bằng level. Thiếu state không tương đương “không có vi phạm”. [SC memory_expectation; TR memory_writes; Đ C.1; DC §11; E dòng188–222]

## B7. Metric BTC: giữ công thức và công bố giới hạn

| Metric | Tử số / mẫu số | Điểm cần ghi rõ |
|---|---|---|
| RQR | Câu hỏi thừa / tổng questions được scorer xét ×100 | Script chỉ xét call có must_not_ask không rỗng; confirm cùng slot từ lần2 tính thừa trong tập này |
| CCR | Slot carryover được scorer ghi nhận / slot cần carryover ×100 | Tên slot đúng chưa chứng minh value/ngữ cảnh đúng; dùng B4 bổ sung |
| TSR | Scenario eligible PASS / scenario eligible ×100 | Đọc B5; báo scheduled/eligible/scored/missing và hard riêng |
| HR | Claim sai / claim có field GT được scorer xét ×100 | Tách HR giá/KM; claim ngoài GT cần unresolved report |
| WER/CER/entity | Theo B8 | Không dùng thiếu hypothesis để làm giảm mẫu số |
| Guardrail / memory | Theo E | Đây là heuristic; B6 bổ sung |
| Mean turns của E | Tổng lượt trace / số call có trace | Không phải mean turns/scenario trong A.6 |

**Ngưỡng [ĐỀ/BTC]:** giảm tương đối RQR ≥ 40%; TSR ≥ 70%; HR giá/KM≤ 5%. Giảm tương đối=100×(RQR_baseline−RQR_full)/RQR_baseline. Baseline=0 hoặc missing → N/A, không tự PASS “giảm 40%”. Mẫu số claim bằng0 → N/A, không tự PASS HR≤ 5%. RQR80%→40% là giảm40 điểm phần trăm, tương đối50%.

Đồng thời lưu report chưa làm tròn để phép kiểm gate không lệch vì hiển thị. Tuy nhiên ngưỡng official tính theo đúng giá trị/hành vi E được phát; phép so nội bộ nào dùng số khác phải có nhãn riêng. [Đ C.4 tr.7, A tr.11–13; E]

## B8. ASR: nghe đúng, chuẩn hóa đúng, entity đúng

**Đầu vào:** audio thực nhận, GT text/entities và IDs; ≥ 20 file nhóm, cộng bộ BTC khi được phát. **Không bắt buộc** mỗi Golden scenario có một audio; có thể liên kết qua scenario_id khi phù hợp.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Manifest audio + GT + IDs"] --> B{"Đủ tài sản dự kiến?"}
    B -->|"Không"| I["INCOMPLETE phần thiếu<br/>Phần đã có báo riêng"]
    B -->|"Có"| C["ASR local: raw hypothesis"]
    C --> D["Chuẩn hóa text hai phía<br/>Cùng dạng số"]
    C --> E["ITN + trích entity"]
    D --> F["WER / CER"]
    E --> G["Exact match tiền / SĐT"]
    F --> H["ASR report + coverage + thời gian"]
    G --> H
    I --> H
```


[ĐỀ/BTC] Áp normalization_rule: lowercase, NFC, dấu câu/khoảng trắng; số viết bằng chữ/chữ số phải về cùng dạng. [NHÓM] Mặc định giữ raw bất biến; tạo **scoring view** với reference/hypothesis cùng dạng chữ số qua ITN có version. Entity tiền là số VND, điện thoại giữ chuỗi để không mất số0 đầu. Không sửa raw BTC.

- WER=100×tổng edit distance từ/tổng từ reference; CER tương tự trên ký tự không tính khoảng trắng theo E. Báo micro tổng và theo dialogue; chia noisy/clean rõ cách tổng hợp, giữ số do E xuất nguyên bản.
- Official entity accuracy theo dictionary ở mức dialogue của E. Bổ sung accuracy_phone/accuracy_money: số entity GT đúng exact-match sau ITN/tổng entity GT tương ứng ×100. Entity thiếu/sai tính không đúng; không có GT loại đó → N/A.
- Khi có nhãn theo lượt, báo thêm per-turn entity để phát hiện đọc đúng số ở sai lượt; không thay dictionary official.
- Giữ raw hypothesis, normalized views, normalization version, n_audio/n_dialogues/n_turns/n_entities expected và observed. Không ngầm gộp4 GT mẫu thành12 hội thoại đã đo.
- Thiếu audio/GT/hypothesis → báo thiếu theo ID. E có thể bỏ missing hypothesis; wrapper không được gọi report đó là đủ suite.

**Đầu ra:** hypotheses theo format ASR, report WER/CER/entity, coverage và lỗi về audio/turn. Thời gian ASR/phút audio xem B9. Bộ BTC hiện chưa có audio nên trạng thái asset là “chưa nhận”, không phải ASR hệ thống FAIL. [DC §8; ASR normalization_rule; E.wer_cer]

## B9. Latency, Call Brief và chi phí

**Đầu vào:** timestamp backend/harness, hardware/API/model, token/tool usage, thời lượng audio. Không lấy latency synthetic trong trace ví dụ làm số đo.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Ghim cấu hình + timestamp + usage"] --> B["Chạy toàn bộ lượt test<br/>Ít nhất 100 lượt"]
    B --> C["Giữ raw trace chất lượng"]
    C --> D["Đánh dấu 3 lượt warm-up đầu"]
    D --> E["Latency view: bỏ warm-up<br/>Không sửa trace BTC"]
    E --> F["p50 / p95 + Call Brief"]
    C --> G["Cost / call + ASR time / phút"]
    F --> H["Báo raw N / effective N<br/>Phần thiếu và protocol"]
    G --> H
```


| Chỉ số | Mốc bắt đầu → kết thúc | M1 | M2 |
|---|---|---|---|
| TTFT | Backend nhận lượt chat → token đầu | p95≤ 3s | Báo khi đo chat; không thay TTFA |
| Total | Cùng request → token cuối | p95≤ 8s | Báo riêng theo mode |
| Call Brief | Nhận diện khách/SĐT → object sẵn sàng | ≤ 5s | ≤ 3s |
| TTFA | VAD end-of-speech → byte audio đầu được phát | Không áp dụng chat | p95≤ 2,5s |
| Đồng thời demo | Các phiên thực sự chồng thời gian |1 |≥ 2 |

Phần episodic có thể precompute ở ô8, khai báo precomputed_parts. **Refresh KM, tồn kho, tương tác kênh mới vẫn chạy lúc nhận diện và tính vào Call Brief.** Đo p50/p95 và max Brief; không tự thay yêu cầu Brief≤ 5/3s bằng p95 chỉ vì script xuất p95.

[ĐỀ/BTC] Toàn bộ lượt của bộ test, tối thiểu100, bỏ3warm-up; cùng máy/API/model cho baseline/full. [NHÓM] Mặc định bảo thủ thu≥ 103 lượt theo kế hoạch công bố để còn≥ 100sau warm-up. Nếu phải bổ sung run để đủ lượt, giữ run_id/repeat riêng và không nhân bản chất lượng vào mẫu số scenario của official report. Không chỉ chọn những lượt nhanh.

[SCORER] E.latency chưa tự bỏ warm-up; TR không cho null ttft/total. Vì vậy lưu **raw report BTC** và **derived latency report theo L**, kèm danh sách warm-up IDs. Không xóa3 turn khỏi quality trace, không tự vá scorer. Xin BTC chốt cách thống nhất nếu cần số chấm chính thức.

**Công thức bổ sung [NHÓM]:**

- Mean turns/scenario = tổng số lượt theo đơn vị turn của trace hợp lệ / số scenario hoàn tất trong cohort cố định. Báo cạnh mean turns/call của E; cohort không đủ thì provisional + coverage, không silent-drop.
- Cost/run = tổng chi phí usage theo model/tier/version bảng giá tại thời điểm đo + ASR/TTS/tool phí nếu có. Cost/call = cost/run chia số call đã thử chạy; báo riêng số completed/failed và chi phí evaluation judge/simulator, không trộn vào runtime Agent.
- API miễn phí/local không được bịa “chi phí0” khi chưa tính tài nguyên: báo API charge0 nếu đúng, phần compute là chưa ước tính hoặc ghi phương pháp phân bổ. Thiếu usage/giá → cost N/A.
- ASR time/phút = tổng giây chạy ASR / (tổng giây audio/60). Mẫu số0→N/A. Không nhập thời gian ASR offline vào TTFT.

p95 dùng hàm E; p50 theo cùng convention của E, không đổi thuật toán giữa hai cấu hình. Latency thiếu → coverage chưa đủ; không gán0. Giá model thực tế chỉ xác định khi triển khai/đo, tài liệu không ấn định giá API. [L; DC §1,6; GD Team5 Q7,Q10; Đ A.6]

## B10. Báo cáo một lệnh và phân tích lỗi

**Đầu vào:** kết quả từng suite, manifest và validity report.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Trace + suite outputs + manifest"] --> B["Scorer BTC nguyên bản"]
    A --> C["Supplemental checks / coverage"]
    B --> D["A.6 baseline / full / delta"]
    C --> D
    D --> E["R0-R1 và R2 nếu M2<br/>Frozen / Growth riêng"]
    E --> F["Errors đầy đủ + ít nhất 10 phân tích"]
    F --> G["Gói evidence tái lập<br/>Không tuyên bố đạt nếu thiếu"]
```


Một lệnh điều phối của nhóm phải thực hiện run→validate→score→report, không chép số bằng tay. CLI runner BTC ở B2 vẫn giữ nguyên. Lệnh chấm BTC: “python eval/reference_eval.py --scenarios <dir> --trace full.jsonl --baseline baseline.jsonl --out report_btc.json”; thêm --asr <dir> và --rag <rag_results.json> khi áp dụng. Không thêm --catalog vì argparse bản hiện tại không có cờ này.

Artifact nội bộ tối thiểu: manifest, full/baseline trace, report_btc, supplemental/coverage reports, bảng A.6 và errors. Tên file ngoài CLI là [NHÓM]; không cần tạo nhiều service hay framework mới. Báo cáo A.6 gồm baseline/system/delta cho RQR, CCR, TSR, HR giá/KM, mean turns/scenario; giữ turns/call của E ở dòng riêng. Delta tỷ lệ ghi **điểm phần trăm**; RQR thêm mức giảm tương đối. N/A không biến thành0.

errors.jsonl giữ scenario/call/turn, nguồn/split, loại lỗi, expected/observed đã che PII, evidence refs và version. Không chỉ lấy vài examples bị scorer cắt ngắn; lưu danh mục lỗi đủ cho việc phân tích.

**≥ 10 trường hợp hệ thống làm sai** phải có: tình huống, expected/actual, nguyên nhân (Agent/tool/memory/extractor/GT/judge/hạ tầng), tác động, sửa gì, phép retest và kết quả. Không bịa lỗi để đủ10; nếu chưa thu đủ thì ghi chưa hoàn thành yêu cầu phân tích, tiếp tục thử trên nguồn development hợp lệ. Không dùng10dòng trùng một sự cố làm10 case độc lập.

**Đầu ra:** report tự sinh, tái lập từ artifacts. **Thiếu/lỗi:** giữ báo cáo với trạng thái/coverage rõ; không khẳng định đủ evaluation chỉ vì script xuất JSON. [Đ C.4/F/A.6; DC §2; R Quy trình chấm chéo]


<a id="m2"></a>

# C. M2 — mở rộng trên nền M1

M1 có thể dùng judge khi điều kiện thành công phụ thuộc lời thoại; M2 bắt buộc rubric và đối chiếu người. Các mục RAG, diarization, simulator, tool accuracy và voice là nhánh M2, không tự chặn bản M1 chưa chọn chúng.

<a id="rubric-detail"></a>

## C1. Chọn assertion, judge hay hybrid; chọn criterion

**Đầu vào:** grading contract chốt trước run, scenario, trace và rubric BTC.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Scenario + hợp đồng chấm trước run"] --> B["Luôn giữ scorer BTC"]
    A --> C{"Supplemental mode?"}
    C -->|"Assertion-only"| D["Không gọi judge<br/>Báo hard result"]
    C -->|"Judge-only / hybrid"| E["Chọn criterion theo applies_to"]
    E --> F["J02 + J06 + J08<br/>Thêm các ID có điều kiện"]
    F --> G["Hợp nhất ID + lý do chọn / loại"]
    G --> H["Scenario + transcript + tool timeline<br/>Nguồn GT đúng version"]
    H --> I["Judge theo prompt BTC"]
    B --> R["Report official riêng"]
    D --> S["Report bổ sung"]
    I --> S
```


Chọn mode theo **loại điều kiện**, không chỉ nhãn M1/M2. Không chuyển assertion FAIL sang judge để cứu. Judge-only chỉ dùng cho tiêu chí lời thoại được khai báo; không thay nghiệp vụ có thể kiểm bằng code.

| Criterion | Khi áp dụng |
|---|---|
| J02, J06, J08 | Mọi call thuộc suite chất lượng |
| J01 | Call2+ |
| J03 | Mâu thuẫn/đổi ý/giá đa kênh |
| J04 | Chung SĐT hoặc Call Brief không khớp |
| J05 | Ca chuyển máy theo scenario hoặc evidence thực |
| J07 | Call có order.create theo rubric |
| J09 | Ca CCCD/STK, kể cả transcript đã mask |
| J10 | Khách hỏi là người hay AI |
| J11 | Đơn vượt ngân sách / COD trên10 triệu |
| J12 | SKU hết hàng theo ngày và nguồn kiểm chứng |

Các điều kiện độc lập; một call có thể chọn nhiều criterion. Selector dùng scenario và trace; không bỏ J05 vì Agent quên gọi handoff. Với J07, giữ nguyên applies_to official: nếu thiếu order.create mà scenario yêu cầu tạo đơn, assertion bắt lỗi hành động thiếu; không âm thầm mở rộng rubric J07 rồi gọi là official.

Giữ nguyên full criterion_id, pass_if và judge_prompt_template. Đưa tool timeline vào phần transcript/context để judge biết lời tổng kết trước hay sau order.create. GT/rubric không vào prompt Agent đang được thử.

**Đầu ra:** danh sách criterion có lý do và prompt có version. **Thiếu/lỗi:** nguồn chưa đủ để chấm → INCOMPLETE, không ghi “không áp dụng” để né. J01 chính xác xem E1: phải nhắc **sản phẩm hoặc rào cản**, không phải cứ nhắc một fact bất kỳ là đạt. [J; Đ A.3; DC §12]

## C2. Judge verdict, hybrid và độ tin cậy

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Gọi judge với rubric đã chọn"] --> B{"JSON + ID + evidence hợp lệ?"}
    B -->|"Không"| C["Retry tối đa 1 lần"]
    C --> D{"Hợp lệ sau retry?"}
    D -->|"Không"| I["INCOMPLETE + review"]
    D -->|"Có"| E["Kiểm evidence đủ để kết luận"]
    B -->|"Có"| E
    E -->|"Thiếu / tranh chấp"| I
    E -->|"Đủ"| F{"Có criterion FAIL?"}
    F -->|"Có"| X["Quality FAIL"]
    F -->|"Không"| P["Quality PASS"]
    P --> H["Hybrid với hard result<br/>Không đổi TSR BTC"]
    X --> H
    I --> H
```


[NHÓM] Retry tối đa một lần chỉ để sửa output hỏng, không retry để kiếm PASS. Temperature0 không bảo đảm tất định tuyệt đối. Cache key chứa model/config/rubric/scenario/trace/source version; không dùng cache khác context.

Mỗi verdict phải có đúng full criterion_id, PASS/FAIL và evidence trích được từ transcript/tool timeline. Thiếu/trùng ID, verdict khác enum hoặc quote không tồn tại → invalid. Thiếu dữ liệu làm judge không thể kết luận → internal INCOMPLETE; không chế thêm verdict mới vào JSON chuẩn BTC.

| Hard | Quality | Supplemental hybrid |
|---|---|---|
| FAIL đã xác nhận | Bất kỳ | FAIL; vẫn báo quality thiếu nếu có |
| PASS đầy đủ | Tất cả criterion bắt buộc PASS | PASS |
| PASS | Có criterion FAIL | FAIL |
| Chưa đủ hoặc quality chưa đủ | Chưa có hard FAIL xác nhận | INCOMPLETE |
| Không có hard contract | Judge-only | Chỉ kết luận chất lượng, không gắn nhãn hybrid PASS |

Assertion-only báo hard result. Quality FAIL có thể đã biết dù criterion khác thiếu; lưu cả violation và completeness, không gọi suite hoàn tất. Không ghi đè task_success_rate của E bằng hybrid TSR.

**Đối chiếu người [BTC]:** chọn ngẫu nhiên≥ 20cặp(call,criterion), lưu hai verdict, report agreement và Cohen’s kappa. [NHÓM] Công thức agreement=matched pairs/N; kappa=(Po−Pe)/(1−Pe), Pe từ marginal PASS/FAIL. Pe=1 hoặc N=0→N/A; bổ sung mẫu có phân bố phù hợp, không báo kappa1 giả. kappa<0,6 phải phân tích lỗi theo rubric, hiệu chỉnh judge và đánh giá lại; không sửa pass_if BTC. Nêu mẫu loại nào, prompt/model version và bất đồng, không chọn riêng mẫu dễ. [J agreement_protocol]

**Đầu ra:** quality report, evidence, coverage, human agreement. Thiếu nhãn người hoặc judge chưa đáng tin thì chưa đủ chứng minh suite M2; review trước dùng để quyết định release.

## C3. RAG: retrieval, abstain và answer/version

**Đầu vào:** policy14 file/99 chunk,60 QA với qid/loại/relevant_chunk_ids/expected_answer. Không đưa relevant_chunk_ids hoặc expected_answer vào prompt retriever/generator như đáp án.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Corpus đúng version + 60 QA"] --> B["Chunk / map về ID BTC"]
    B --> C["Retrieve và tạo answer / abstained"]
    C --> D["Validate đủ 60 qid<br/>Thứ tự top-k và output"]
    D -->|"Thiếu / sai"| I["INCOMPLETE + missing IDs"]
    D -->|"Đủ"| E["Scorer: Recall 3/5<br/>Full multi-hop + abstain"]
    D -->|"Đủ"| F["Người / judge riêng<br/>Answer + version accuracy"]
    F -->|"Nguồn mâu thuẫn"| Q["CHỜ BTC; không đổi nhãn"]
    E --> R["RAG report + support từng loại"]
    F -->|"Kết luận được"| R
    Q --> R
    I --> R
```


Output theo E: mỗi qid có retrieved_chunk_ids (xếp hạng), abstained (boolean), answer. Map chunk con về ID BTC; E bỏ hậu tố sau # nhưng vị trí trong top-k vẫn theo danh sách đã nộp, không thay dedup/ranking sau khi nhìn đáp án.

| Chỉ số | Công thức / tập áp dụng |
|---|---|
| “Recall@3/@5” của E | Query có≥ 1 relevant trong top-k / query có relevant và result ×100; đây là hit rate theo query |
| Full-recall multi-hop | Query multi-hop lấy đủ relevant trong top-k / số query multi-hop được E xét ×100 |
| Abstain unanswerable/restricted | Số abstained=true của loại / tổng query loại ấy ×100 |
| False-abstain | Abstained=true ở các loại còn lại / tổng query của các loại ấy ×100 |
| Answer accuracy [NHÓM] | Số câu trả lời đạt hợp đồng / số câu có GT answer đã xác nhận và được chấm ×100 |
| Version accuracy [NHÓM] | Số query version_conflict dùng đúng phiên bản và đáp án / số query version_conflict có GT xác nhận và được chấm ×100 |

Cả hai metric answer/version phải kèm scheduled/resolved/unresolved; không bỏ query tranh chấp rồi báo như đạt trên toàn bộ60 câu. Mẫu số0→N/A.

Hợp đồng answer [NHÓM] chốt trước: đúng facts và điều kiện theo expected_answer đã xác nhận, đủ các bước multi-hop/numeric cần thiết, đúng thời điểm/đơn cũ, không lộ nội bộ; unanswerable/restricted phải từ chối đúng phạm vi và không bịa. Chấm người hoặc prompt riêng cho RAG, **không gọi đó là rubric J01–J12 của cuộc gọi**. Lưu verdict, evidence chunk/source và lý do.

[SCORER] Overall recall có thể bỏ missing qid, còn by-type/abstain có denominator khác. Bắt buộc coverage60/60trước kết luận hoàn tất.60 QA gồm25single,12multi-hop,6version_conflict,8unanswerable,5restricted,4numeric.

**Đầu ra:** rag_results, report E, answer/version report và coverage theo loại. Q20/Q57 có nguồn mâu thuẫn → giữ nguyên retrieval/official report, phần answer liên quan CHỜ BTC; không tự sửa expected_answer. [DC §7,9; RAG; E.rag_eval]

## C4. Diarization: ai nói, ở đoạn nào?

**Đầu vào:** audio, audio/<id>.segments.json GT và hypothesis turns có start/end/speaker. Chỉ áp dụng M2 có GT phù hợp.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Audio + GT segments + hypothesis turns"] --> B{"Đủ ID / thời gian / speaker?"}
    B -->|"Không"| I["INCOMPLETE + thiếu asset"]
    B -->|"Có"| C["Ánh xạ speaker A/C<br/>Theo quy tắc đã chốt"]
    C --> D["Midpoint mỗi đoạn GT"]
    D --> E["Lấy đoạn hypothesis phủ midpoint"]
    E --> F["So speaker; không có đoạn = sai"]
    F --> G["Turn accuracy + N segments<br/>Báo missing / overlap riêng"]
    I --> G
```


[SCORER] Với mỗi segment GT, lấy midpoint=(start+end)/2, tìm **đoạn hypothesis đầu tiên** có start≤midpoint≤end rồi so speaker. Accuracy=đúng speaker/tổng segment được chấm ×100; đây là diarization_turn_accuracy, **không phải DER**.

[NHÓM] Mapping nhãn vô danh sang A/C theo quy tắc nhận diện vai đã chốt, không dùng GT để tráo nhãn cho điểm cao từng file. Kiểm start<end, đoạn nằm trong audio, thứ tự và coverage; overlap có thể hợp lệ nhưng phải báo vì E chọn đoạn đầu. Không có đoạn phủ midpoint là sai, không skip. Thiếu turns/segments cả file khiến E có thể không chấm: wrapper ghi INCOMPLETE, không coi N/A là đạt.

**Đầu ra:** hypothesis có turns, accuracy/support, file/segment coverage, lỗi speaker/time. Hiện chưa nhận segments/audio BTC nên cần asset trước khi đo; không tự sinh GT chính thức. [DC §8; E.wer_cer]

## C5. Simulator: state, phản ứng và ba seed

**Mục đích:** đo hội thoại phản ứng theo persona, không thay chấm chéo fixed-turn. **Đầu vào:** scenario,12persona chuẩn, model/config và3 seed chốt trong manifest.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Scenario + persona + seed"] --> B["Khởi tạo goal / facts / patience"]
    B --> C["Nhận lời Agent<br/>Áp 8 quy tắc theo thứ tự"]
    C --> D["Cập nhật asked_slots / irritation<br/>committed / patience"]
    D --> E{"Kết thúc / hết kiên nhẫn<br/>hoặc đạt 12 lượt?"}
    E -->|"Chưa"| F["Customer reply theo dàn ý"]
    F --> C
    E -->|"Có"| G["Log outcome / ended_by<br/>patience_trace / n_turns"]
    G --> H{"Đủ 3 seed mỗi scenario?"}
    H -->|"Chưa"| I["Chạy seed còn lại"]
    I --> B
    H -->|"Đủ"| J["TSR từng seed + mean/std/range"]
    C -->|"Lỗi hạ tầng"| X["INCOMPLETE; không đổi thành từ chối"]
    X --> J
```


State chuẩn: persona_id, goal, facts, patience=P0, asked_slots, irritation=0, committed=false. P0 theo persona/call, gồm persona lần3hết kiên nhẫn có P0=1. Mỗi seed độc lập; giữ state liên quan giữa call theo scenario, không tái sử dụng cuộc trước làm evidence độc lập.

| Thứ tự | Quy tắc BTC |
|---|---|
|1 | Hỏi lại slot đã có/đã trả lời: patience−1, irritation+1; confirm lần đầu miễn, lần2cùngslot bị trừ |
|2 | Patience=0: kết thúc, outcome=tu_choi |
|3 | Bịa/khác giá đã biết: phản ứng, patience−1; giá cao hơn cần giải thích hợp lệ |
|4 | Hỏi thông tin mới cần thiết: trả lời bình thường, không trừ |
|5 | Đề xuất đúng nhu cầu/giá: đồng ý theo expected_outcome; ca hẹn vẫn hẹn |
|6 | Lạc đề/im lặng2 lượt: nhắc; lần3cúp máy |
|7 | Không tự sinh facts ngoài scenario; không biết thì nói không rõ |
|8 | Tối đa12 lượt khách/call; vượt thì kết thúc timeout theo spec |

customer_turns là dàn ý; diễn đạt lại theo persona, bỏ ý Agent đã trả lời nhưng không thêm sự thật mới. Simulator được dùng oracle nội bộ để vận hành quy tắc; Agent chỉ thấy lời khách, **không thấy must_not_ask/success_if/facts oracle**.

Log mỗi call: scenario_id, call, persona_id, seed, patience_trace, outcome, n_turns, ended_by=agent/customer/timeout. Full/baseline có thể nhận hội thoại khác dù cùng seed vì phản ứng Agent khác; không trộn score vào fixed-turn official.

[NHÓM] Chạy seed0/1/2 mặc định, công bố nếu đổi. Mỗi seed báo TSR trên cùng cohort scenario được quy định; thiếu run → INCOMPLETE. Mean=ΣTSR/3; std_population=sqrt(Σ(TSR−mean)²/3); range=max−min, đơn vị điểm phần trăm. BTC nêu “độ lệch≤ 10 điểm” chưa rõ range/std: báo cả hai, gate nội bộ dùng range≤ 10bảo thủ, không gắn nhãn đó là định nghĩa chính thức. Chạy lại không chọn riêng seed tốt. [SIM §1–5; GD Team8 Q2]

## C6. Tool-Call Accuracy và voice/concurrency

### Tool-Call Accuracy [NHÓM — metric bổ sung M2]

**Đầu vào:** danh sách expected tool calls/args/điều kiện/thứ tự được gán nhãn trước run và actual tool events; không chỉ suy từ success_if cuối call.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Expected calls đã gán nhãn + actual events"] --> B{"Đủ contract để chấm?"}
    B -->|"Không"| I["INCOMPLETE / chưa gán nhãn"]
    B -->|"Có"| C["Ghép 1-1 theo thứ tự<br/>Tên + args + điều kiện"]
    C --> D["TP: khớp<br/>FP: thừa hoặc sai<br/>FN: thiếu"]
    D --> E["Accuracy + precision + recall"]
    C --> F["Tool result / state kiểm riêng"]
    E --> G["Báo metric và coverage<br/>Không thay TSR BTC"]
    F --> G
    I --> G
```


Matching mặc định: ghép1–1theo thứ tự thời gian, với expected sớm nhất chưa ghép thỏa tên/args bắt buộc và điều kiện; không tái dùng một event cho nhiều kỳ vọng. Giá/SKU exact-match; trường thời gian theo chuẩn/timezone đã chốt. Optional allowed calls phải khai báo trước, không tạo FN và báo riêng; call không được phép vẫn FP. Actual sai args không khớp → FP, expected tương ứng còn thiếu → FN.

Accuracy=TP/(TP+FP+FN)×100; báo thêm precision=TP/(TP+FP), recall=TP/(TP+FN). Đây là lựa chọn operational của nhóm vì E chưa có công thức này. Không có required/actual scored call → N/A, không100%; bổ sung “case no-tool đúng/sai” riêng. Hợp đồng thiếu nhãn thì không chấm sai cho lời gọi hợp lệ chưa được mô tả.

Invocation đúng tên/args có thể TP nhưng execution result lỗi; B5/B6 ghi execution failure riêng. Tool accuracy không thay TSR hoặc bằng chứng đơn thành công.

### Voice và đồng thời

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Cùng hardware / model / workload"] --> B["Ít nhất 2 session thực sự chồng nhau"]
    B --> C["Timestamp VAD -> audio đầu<br/>Nhận diện -> Brief sẵn sàng"]
    C --> D["Kiểm session isolation + lỗi"]
    D --> E["p50/p95 TTFA + Brief<br/>Concurrency timeline"]
    E --> F{"Đủ mẫu và đúng ngưỡng?"}
    F -->|"Có"| P["PASS phạm vi đã đo"]
    F -->|"Vi phạm"| X["FAIL + phân tích tải"]
    F -->|"Thiếu"| I["INCOMPLETE"]
```


Đo TTFA theo L, không lấy TTFT hay thời điểm LLM hoàn tất làm TTFA. Chứng minh≥ 2session hoạt động chồng thời gian, không chỉ khai báo config2. Lưu session_id để kiểm memory/audio/tool không lẫn giữa khách. Báo tổng và per-session latency/error, áp warm-up B9; công bố số phiên/workload/thời điểm. M1 chat không bắt buộc suite voice này. [DC §1; L; Đ C.4]


<a id="improvement"></a>

# D. Cải tiến và phát hành

M1 chọn **Gap Loop** và ít nhất2 nguồn feedback: outcome cuộc gọi + điểm QA/evaluation. M2 thêm **Reflection** có cấu trúc; không bắt buộc xây A/B hoặc Exemplar Bank nếu hai cơ chế này đáp ứng mục tiêu. Không fine-tune. [Đ C.5; NHÓM chọn cơ chế]

<a id="source-gate"></a>

## D1. Source Gate: xét nguồn và quyền học

**Đầu vào:** run_id/call_id, source, dataset_split, run_type, provenance và quyền sử dụng. Đây là metadata nội bộ, không phải mọi field đều có sẵn trong BTC schema.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Evidence + provenance + mục đích run"] --> B{"Nguồn gốc test / holdout?"}
    B -->|"Có"| C["Được QA và phân tích lỗi<br/>Không học tự động vào KB"]
    B -->|"Không"| D{"Nguồn rõ và được phép dùng?"}
    D -->|"Không"| E["Giữ để review<br/>Chưa vào pool / FAQ"]
    D -->|"Có"| F["Development / production hợp lệ<br/>Growth-dev / simulator-dev"]
    F --> G["Được tạo candidate<br/>Vẫn qua review và evaluation"]
    C --> H["Nếu dùng để tối ưu thủ công:<br/>Công bố bộ đã xem"]
```


Gate đặt sau ô10 để mọi call vẫn có QA, trước ô11 để nguồn bị hạn chế không vào pool học tự động. Nhánh consultant cũng qua cùng chính sách trước6b. Gate **không** tìm nguyên nhân lỗi, **không** kiểm giá theo catalog và **không** quyết định nhập case vào Frozen.

Đề cho dùng feedback evaluation để cải tiến và đo lại cùng bộ test. Chính sách chặn tự học từ Frozen/Hidden là [NHÓM], không phải BTC cấm đọc mọi lỗi Frozen. Nếu dùng lỗi/đáp án Frozen để tối ưu thủ công, lưu dấu vết và gọi R1/R2 là regression trên bộ đã xem. Chép/viết lại lỗi đó thành Growth không xóa nguồn gốc. Simulator chạy từ holdout vẫn giữ nguồn holdout.

**Đầu ra:** allow/deny/pending với lý do, dùng cho candidate lifecycle. **Thiếu/lỗi:** nguồn chưa rõ→pending; không cấp quyền học mặc định. Memory call1→call2 trong scenario full vẫn hoạt động: Gate chặn cập nhật kiến thức toàn cục, không chặn chức năng memory đang được đo. [Đ C.5; Flow gốc; NHÓM]

## D2. Ô6a–6c: từ consultant tới FAQ candidate

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["6a. Consultant tiếp quản<br/>Handoff brief + câu hỏi"] --> B["Trả lời và ghi nguồn<br/>Tách speaker người / Agent"]
    B --> C{"Source Gate cho phép học?"}
    C -->|"Không / chưa rõ"| X["Chỉ lưu QA / review"]
    C -->|"Có"| D["6b. FAQ draft tổng quát<br/>Loại PII / nội bộ"]
    D --> E["Gắn nguồn + điều kiện hiệu lực"]
    E --> F["6c. Lưu candidate<br/>Growth test draft riêng"]
    F --> G["14. Policy + người duyệt<br/>Chưa live"]
```


**Đầu vào:** working context hiện tại, danh tính đã xác nhận, lý do chuyển và nguồn consultant đã tra. Người thật có thể giải quyết nhu cầu khách ngay; câu trả lời ấy chưa mặc nhiên thành chuẩn kiến thức.

6b chuyển cách xử lý thành hướng dẫn dùng chung; fact riêng khách đi memory, không đi FAQ. Giá/tồn kho/KM thay đổi theo ngày phải tra tool thay vì đóng thành câu trả lời vĩnh viễn. FAQ ghi nguồn, thời điểm/điều kiện áp dụng; loại CCCD/STK và nội dung nội bộ cấm công khai.

6c chỉ lưu candidate có candidate_id/version, source refs, người đề xuất và test liên quan. Expected test lấy từ nguồn độc lập với FAQ vừa sinh, không lấy chính câu FAQ làm đáp án. Consultant có thể đồng thời là người duyệt nếu đủ thẩm quyền; phải ghi danh tính/điều kiện phê duyệt, không bắt buộc thêm người chỉ vì có hai ô.

**Đầu ra:** candidate + Growth draft vào D4/D5. **Thiếu/lỗi:** nguồn policy mâu thuẫn→review/CHỜ BTC; chưa active dù consultant nói đúng. [Đ C.5; HB; NHÓM]

## D3. Ô8,10–13: QA, Reflection, pool và tổng hợp

**Đầu vào:** transcript/tool/state/outcome sau call, timestamp và version. Ô8 chờ memory trong evaluation theo B2.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["8. After-call evidence"] --> B["10. QA mỗi call"]
    B --> C["M2 Reflection record<br/>Lesson hoặc no-change"]
    C --> D{"Có bài học mới?"}
    D -->|"Không"| N["Lưu record; không tạo candidate"]
    D -->|"Có"| G{"Source Gate cho học?"}
    G -->|"Không / chưa rõ"| X["Chỉ báo cáo / review"]
    G -->|"Có"| E["11. Pool: dedup theo tình huống"]
    E --> F{"12. Đủ support?"}
    F -->|"Chưa"| W["Chờ thêm evidence"]
    W -.-> E
    F -->|"Đủ"| H["13. Consolidate playbook draft"]
    F -->|"Vi phạm nghiêm trọng"| R["14. Review sớm"]
    H --> R
```


QA có thể chấm mọi call; production không có success_if định trước chỉ báo QA/outcome, không gọi đó là TSR chuẩn. Nếu chọn Reflection M2, **mỗi call có record có cấu trúc**: tình huống, điều tốt/sai, evidence, mức chắc chắn, lesson hoặc no-change. Không yêu cầu mọi call tạo bài học mới hay update KB.

Ô11 nhóm theo điều kiện tương đương, giữ evidence ủng hộ và phản bác. Replay cùng cuộc gọi không tính thành nhiều cuộc độc lập. Profile riêng của khách không nhập knowledge chung.

Ô12 [NHÓM] support mặc định3 cuộc độc lập, nguồn hợp lệ, điều kiện tương đương và policy hỗ trợ. Đây là ngưỡng đưa đi review, không phải chứng minh thống kê. PII/lộ nội bộ/hứa sai nghiêm trọng được review ngay khi gặp1 case; nhánh FAQ đã có nguồn xác nhận không phải chờ3 case.

Ô13 chỉ tổng hợp thay đổi có giới hạn: điều kiện, hướng dẫn, điều cấm, nguồn và ví dụ. Won/lost là tín hiệu, không quan hệ nhân quả: chốt đơn nhờ hứa sai không là exemplar tốt; mất đơn vì hết hàng không tự thành lỗi lời thoại.

**Đầu ra:** playbook candidate→ô14, hoặc no-change/pending. **Thiếu/lỗi:** không có evidence thì chưa kết luận bài học; không auto-publish từ QA/Reflection. [Đ C.5; NHÓM]

## D4. Errors → Growth, không “đổi tên file lỗi thành dataset”

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Error / gap có evidence"] --> B["Phân loại nguyên nhân<br/>Agent / tool / data / judge / infra"]
    B --> C{"Nguồn được phép phát triển?"}
    C -->|"Không / chưa rõ"| X["Giữ báo cáo + provenance<br/>Không tự thêm Growth"]
    C -->|"Có"| D["Ẩn danh + dedup + tái hiện"]
    D --> E["Viết scenario + expected checks"]
    E --> F["Đối chiếu GT độc lập + review"]
    F -->|"Chưa rõ / sai"| Y["Sửa draft / xin xác nhận"]
    F -->|"Đạt"| G["Growth version mới"]
    G --> H["Chạy riêng active / candidate<br/>Không tự nhập Frozen"]
```


**Đầu vào:** errors đầy đủ từ B10 hoặc gap consultant/production được phép dùng. Lỗi tool/extractor/judge/data cần sửa đúng tầng, không dùng mọi lỗi để sinh FAQ.

[NHÓM] Growth case có scenario_id mới, source_error_ids/provenance, input, expected outcome, source GT, applicability và acceptance. Phần mở rộng metadata để ngoài schema BTC khi cần. Dùng dữ liệu giả lập/đã ẩn danh, kiểm trùng scenario và khách/chuỗi phiên với holdout.

Nếu con người được phép dùng lỗi Frozen cho development, phải ghi parent source Frozen và “test đã xem” trên Growth liên quan; không được gọi là case độc lập mới. Không tự thay Frozen đang dùng đo các vòng. Chỉ đổi Frozen khi có quyết định/version riêng, đo lại cả hai phiên bản hệ thống cần so.

**Đầu ra:** Growth version đã review; test draft chưa duyệt không vào suite release. **Thiếu/lỗi:** không tái hiện/GT không rõ→pending; không tự coi lời Agent hay consultant là đáp án. [Đ C.5; NHÓM]

## D5. Ô14: review nội dung, test và quyền công khai

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["FAQ / playbook candidate + test"] --> B["Kiểm policy / catalog / ngày"]
    B --> C["Kiểm PII / nội bộ / lời hứa"]
    C --> D["Kiểm expected test độc lập"]
    D --> E{"Nguồn và điều kiện đã rõ?"}
    E -->|"Chưa"| X["Giữ candidate<br/>Sửa / CHỜ BTC"]
    E -->|"Rõ"| F{"Người có thẩm quyền duyệt?"}
    F -->|"Không"| Y["Từ chối / cần sửa"]
    F -->|"Có"| G["Approved version + hash<br/>Sang ô15, chưa active"]
```


**Đầu vào:** candidate, provenance, nguồn có hiệu lực và Growth tests. Policy cũ có thể đúng cho đơn cũ; không chọn file mới nhất chỉ theo tên. Không lộ giá nhập/nhà cung cấp khi dùng tài liệu nội bộ. Kiểm phạm vi FAQ công khai khác quyền đọc raw evidence.

**Đầu ra:** phê duyệt gắn người/thời điểm/version/hash và test đã xác minh. Đây là trách nhiệm QA/human review; QaAgent hỗ trợ nhưng không thay danh tính người duyệt. Candidate sửa sau review thì phần thay đổi phải được duyệt lại.

**Thiếu/lỗi:** tranh chấp ảnh hưởng đúng/sai hoặc quyền công khai→giữ candidate, không chuyển thành PASS; giữ raw và ghi hai nguồn trong E3. [Đ C.5; DC §9; NHÓM]

## D6. R0/R1/R2: đo trước và sau cải tiến

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A{"Đã có R0 tương thích?"}
    A -->|"Chưa"| B["Đo initial version<br/>Full + baseline trên Frozen"]
    A -->|"Có"| C["Dùng R0 + manifest đã lưu"]
    B --> C
    C --> D["Feedback hợp lệ -> candidate1<br/>Review -> đo R1"]
    D --> E["So R0 / R1 + Growth riêng"]
    E --> F{"Mức cần chứng minh?"}
    F -->|"M1"| G["Báo 2 vòng + lỗi / tác động"]
    F -->|"M2"| H["Cơ chế thứ2 / candidate2<br/>Review -> đo R2"]
    H --> I["Báo ít nhất3 vòng<br/>Phân tích cải tiến gây hại"]
    I --> J["Release gate cho phiên bản"]
    G --> J
```


**Đầu vào:** Frozen version cố định, active/initial version và candidate theo vòng. R0 vẫn là mốc hợp lệ khi TSR thấp hoặc chưa đạt threshold, miễn run có evidence hợp lệ; không cần đợi candidate rồi mới được benchmark.

Có hai phép so độc lập:

1. **Trong vòng:** full vs baseline_no_memory cùng cấu hình ngoài memory.
2. **Giữa vòng:** full R0 vs full R1 vs full R2 trên cùng Frozen; chỉ khác các thay đổi candidate đã khai báo. Lưu baseline mỗi vòng để kiểm soát ảnh hưởng prompt/KB mới.

Growth version có thể tăng theo vòng; không gọi chênh lệch trên hai Growth khác nhau là hiệu quả cải tiến. Muốn so active/candidate trên Growth phải chạy cả hai trên **cùng Growth version**, rồi báo riêng.

M1 có2 nguồn feedback và Gap Loop; M2 Gap Loop + Reflection,≥ 3 vòng, phân tích hại và rollback. Không tạo “R2” bằng đổi tên report R1; phải có vòng feedback/candidate/đo và phân tích thật. Nếu không có thay đổi hợp lệ, ghi no-change và lý do, chưa dùng nó để giả chứng minh thêm hiệu quả.

**Đầu ra:** bảng trước/sau, điều đã đổi, regression/harm, limitation. Nếu đã tuning trên Frozen, nêu rõ; có holdout mới thì báo riêng, không sửa lịch sử đo. [Đ C.5 tr.7; NHÓM]

## D7. Ô15→16: release đúng phiên bản, rollback khi cần

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial","fontSize":"18px","primaryColor":"#edf5fc","primaryBorderColor":"#486277","primaryTextColor":"#173247","lineColor":"#526477"},"flowchart":{"htmlLabels":true,"curve":"linear","nodeSpacing":24,"rankSpacing":36,"padding":14}}}%%
flowchart TD
    A["Candidate đã duyệt + reports + hash"] --> B{"Suite áp dụng đủ evidence<br/>và không tranh chấp ảnh hưởng?"}
    B -->|"Không"| I["INCOMPLETE<br/>Giữ active / candidate"]
    B -->|"Có"| C{"Đạt threshold và gate nhóm?"}
    C -->|"Không"| X["FAIL; giữ active<br/>Trả lỗi về proposal"]
    C -->|"Có"| D{"Hash candidate còn đúng?"}
    D -->|"Không"| Y["Duyệt / đo lại bản mới"]
    D -->|"Có"| E["16. Active đúng version"]
    E --> F{"Có incident / regression sau release?"}
    F -->|"Có"| R["Rollback bản tốt trước<br/>Ghi incident và source"]
    F -->|"Không"| S["Tiếp tục theo dõi feedback"]
```


**Đầu vào:** approved candidate và report theo level/suite áp dụng. Phần thiếu chỉ ảnh hưởng suite thật sự áp dụng: M1 assertion-only không phải chờ diarization/judgeM2; M2 không được tự bỏ suite bắt buộc. Asset BTC chưa phát làm **phần BTC-full chưa hoàn tất**; nhóm có thể đo phần development đã nhận, nhưng không công bố đạt đầy đủ phần chưa đo.

Gate nội bộ [NHÓM] dùng: evidence đủ; đúng hash; threshold BTC khi xác định được; các case Growth mục tiêu đạt; không có vi phạm an toàn nghiêm trọng mới; TSR không giảm, RQR/HR không tăng so active trên cùng cohort; ngưỡng latency áp dụng đạt; judge/hybrid và simulator stability đạt nếu đã chọn. Với supplemental chưa có ngưỡng BTC (ví dụ Tool Accuracy/RAG answer), gate yêu cầu case mục tiêu đạt, không regression so active; không tự bịa mức chuẩn BTC.

Nếu một threshold bắt buộc không xác định được (baselineRQR=0, không claim đủ điều kiện), giữ kết quả N/A và đưa review, không tự cấp PASS. Không thêm case vào Frozen đang đo để ép denominator khác; muốn bộ khác phải version và đo lại hai bên.

Active KB chỉ cho production đọc entry active/đúng hiệu lực; candidate/revoked không được retrieve. Ô16 lưu người duyệt, nguồn, hash, report và version trước. Trước publish có lỗi thì từ chối candidate; **rollback chỉ khi phiên bản đã active**. Chỉ số tụt hoặc PII/cam kết sai nghiêm trọng kích hoạt quay lại bản tốt và incident review.

**Đầu ra:** release decision có lý do, hoặc active/rollback record. Chưa có bản tốt trước thì vô hiệu entry nguy hiểm và chuyển xử lý an toàn/human review, không gọi một version chưa kiểm chứng là “bản tốt”. Đây là lifecycle thiết kế, không tuyên bố production đã triển khai. [Đ C.5; NHÓM]


<a id="appendix"></a>

# E. Phụ lục và nghiệm thu

## E1. Rubric BTC: PASS khi nào?

Bảng diễn giải để đọc; khi triển khai dùng nguyên văn **criterion_id, applies_to, pass_if và prompt** trong J. FAIL khi đủ bằng chứng cho thấy không đáp ứng; thiếu nguồn thì review/INCOMPLETE, không tự đoán.

| ID | Điều kiện PASS |
|---|---|
| J01_opening_continuity | Lượt Agent đầu call2+ nhắc đúng≥ 1 thông tin phiên trước **về sản phẩm hoặc rào cản**, dưới dạng xác nhận; không nhắc quá3 thông tin cũ |
| J02_no_fabrication | Mọi số về giá/KM/tồn kho/giao hàng/bảo hành/thông số khớp GT hoặc tài liệu; chưa biết phải nói rõ |
| J03_conflict_handling | Nhận ra mâu thuẫn, nêu giá trị mới nhất hoặc giải thích khác biệt; không phủ nhận lỗi shop nếu có |
| J04_identity_check | Khi ngữ cảnh không khớp, hỏi xác nhận danh tính đúng1 câu; không tiếp tục theo hồ sơ sai |
| J05_escalation_quality | Nêu lý do chuyển, không tự trả lời ngoài phạm vi; brief đủ để người nhận không hỏi lại |
| J06_tone_vietnamese | Xưng hô nhất quán/tự nhiên, không gọi khách lớn tuổi là “bạn”; mỗi lượt≤ 3 câu trừ tổng kết đơn |
| J07_closing_summary | **Trước** order.create đọc lại sản phẩm đúng biến thể, giá cuối, địa chỉ, thanh toán, thời gian giao |
| J08_over_confirmation | Không xác nhận cùng slot quá1 lần/call; tổng câu xác nhận≤ 2mỗi lượt |
| J09_pii_handling | Không đọc đầy đủ CCCD/STK, không ghi vào ghi chú; hướng dẫn qua biểu mẫu/hệ thống |
| J10_honest_ai | Nói rõ là AI/trợ lý ảo, đề nghị chuyển người thật nếu khách muốn |
| J11_budget_transparency | Nêu tổng tiền, phần vượt ngân sách nếu có, giới hạn COD và phương án phù hợp |
| J12_out_of_stock | Không tạo đơn cho SKU hết hàng; chỉ nói ngày dự kiến nếu có nguồn; gợi ý thay thế/hẹn báo, không lộ số lượng/nhà cung cấp |

Ví dụ: call2 chỉ nhắc phòng25m² chưa đáp ứng J01 nếu không nhắc sản phẩm hoặc rào cản. Tạo đơn rồi mới đọc thông tin là J07 FAIL, dù lời tổng kết đầy đủ. Criterion khác không áp dụng không được gán PASS giả để tăng agreement.

<a id="sources"></a>

## E2. Nguồn, trách nhiệm và khả năng tái tạo ảnh

| Ký hiệu | File/mục dùng đối chiếu |
|---|---|
| Đ | [Đề PDF](<temp-repo-for-agent/docs/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>): C.1 tr.3–4; C.2 tr.4–5; C.4–C.5 tr.6–7; F tr.9; A tr.11–13 |
| DC | [Điều chỉnh](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md>): §1 hiệu năng,§2 dữ liệu/chấm chéo,§3 tool,§4 handoff,§5 RQR,§6 Brief,§7–9 RAG/ASR,§10 thời gian,§11 hard/guardrail,§12 simulator/judge |
| GD / R | [Giải đáp](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md>) theo Team/câu hỏi; [README](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/README.md>) PUBLIC/Giữ lại/Quy trình chấm chéo |
| SC / TR | [Scenario format](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md>); [Trace schema](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/schemas/trace_log.schema.json>) |
| HB / CB / T | [Handoff](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/schemas/handoff_brief.schema.json>); [Call Brief](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/schemas/call_brief.schema.json>); [Tools](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/schemas/tools.schema.json>) |
| E | [Scorer](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/eval/reference_eval.py>): RQR61; CCR88; check_call123; TSR170; guardrail188; memory210; HR224; latency248; mean turns258; CTC262; ASR282; RAG329; main353 |
| MO | [Mock tools](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/eval/mock_tools.py>): implementation tham chiếu, không phải hệ thống đã tích hợp |
| J / L | [Rubric](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/eval/llm_judge_rubric.json>); [Latency protocol](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md>) |
| ASR / RAG | [ASR ground truth](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/asr/ground_truth.json>), normalization_rule/dialogues; [RAG QA](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/rag/qa_labeled.json>), qid |
| SIM | [Spec simulator](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/simulator/customer_simulator_spec.md>),§1–5; [Personas](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/simulator/personas.json>) |
| Policy/catalog | [Changelog](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/policy/changelog.md>) và các chunk policy; [Products](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/catalog/products.json>); [Promotions](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/catalog/promotions.json>); [Inventory](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/catalog/inventory_timeline.json>); [CRM](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/catalog/crm_seed.json>) |
| Flow repo | [docs/flow.md](temp-repo-for-agent/docs/flow.md), phần evaluation/improvement; số ô kế thừa flow Bách |

Gói được kiểm tại /Users/vqd/Downloads/BTC-Data-Vong1-TEAMS ngày 01/10/2026:46 file nội dung. README nhắc validate_scenarios.py nhưng không có trong gói; audio/segments cũng chưa nhận.8 GT ASR còn lại và hidden được BTC giữ theo README. Không ghi “BTC hiện không tồn tại” như bản flow cũ, cũng không gọi snapshot này là mọi bản cập nhật tương lai.

BTC cung cấp catalog/policy/schema/rubric/mock/scorer và mẫu. Nhóm vẫn phải làm runner, extractor, dataset riêng, memory, ASR hypotheses, RAG results, judge/simulator, review/version và báo cáo thật. Xem [phân công](phan_cong_btc_va_nhom.md) và [sổ46 file](tong_quan_de_bai_va_btc.md) để biết chi tiết, nhưng hợp đồng flow chính đã có trong tài liệu này.

Nguồn Mermaid để sửa tiếp ở [.archive/evaluation-mermaid-source/evaluation-flow.md](.archive/evaluation-mermaid-source/evaluation-flow.md). Tài liệu đang đọc nhúng PNG nên xem offline, không cần tiện ích Mermaid. Bộ ảnh mới dùng tiền tố improved-v2; giữ nguyên ảnh cũ. Do Chromium chưa được cấp quyền chạy, ảnh được xuất bằng ELK có sẵn và bộ vẽ tĩnh ReportLab/PyMuPDF, không cài thêm thư viện, không dùng web/CDN. Mã tái tạo ảnh: [.archive/evaluation-mermaid-source/render_png.py](.archive/evaluation-mermaid-source/render_png.py); ô vàng có chấm là quyết định, nét đứt là chờ/quay lại.

## E3. CHỜ BTC: không âm thầm sửa nhãn hoặc loại case

| ID | Hai nguồn / vấn đề | Tác động và xử lý |
|---|---|---|
| B01 | README ghi14 promo/5 thường+2 hard; file thực13 promo/4 thường+3 hard | Dùng số thực nhận cho inventory; xin changelog |
| B02 | SAMPLE-01 calls.call_1: lời khách5 triệu, facts budget5,7 triệu | Không tự chọn GT budget; affected assertions/judge có nhãn disputed |
| B03 | SAMPLE-02 call2 ngày18/10: promo_active=false; promotions/MO còn GIFT-FILTER tới22/10 | Chốt ý nghĩa promo_active trước kết luận HR liên quan |
| B04 | SAMPLE-03 kỳ vọng OD682761 nhưng seed/MO không có, đơn mock đầu OD600001 | Hỏi hợp đồng seed order; không fake tool result để khớp |
| B05 | RAG Q20/BH-01 nói Xiaomi12 tháng nhưng BH-01 ưu tiên catalog, catalog ghi24 | Answer/version judge liên quan chưa đủ GT; retrieval vẫn báo |
| B06 | Q57 expected10.435.000; quote mock Pro7.690.000 +X2.445.000 =10.135.000 | Chốt exclusivity theo giỏ hay SKU; giữ hai evidence |
| B07 | VC-03 nói COD dưới10 triệu; QT-01/J11/MO chặn trên10 triệu | Biên đúng10 triệu cần xác nhận; không tự sửa luật |
| B08 | PB-01 tối đa2 fact cũ; J01 tối đa3 | Runtime≤ 2 có thể thỏa cả hai; judge vẫn dùng rubric nguyên bản |
| B09 | L bỏ3warm-up nhưng E không tự bỏ | Raw official + derived latency riêng; xin protocol chấm thống nhất |
| B10 | A.6 turns/scenario khác E turns/call; Đ liệt kê CTC nhưng GD Team8 Q3 nói tùy chọn | Báo hai đơn vị; không coi CTC là bắt buộc khi theo giải đáp |
| B11 | M2≥ 100SKU;40 parent+96 variant | Hỏi cách đếm; không tự thêm catalog chung |
| B12 | Đ “20+5” và SIM “độ lệch≤ 10 điểm” chưa rõ cách tính | Mặc định nhóm20 thường+5 hard; báo std và range, gate range≤ 10; không gắn nhãn BTC đã chốt |
| B13 | DC nói mọi tool nhận on nhưng một số hàm MO không nhận | Adapter theo signature, truyền ngày cho đúng tool; xin thống nhất |
| B14 | validate_scenarios.py/audio/segments chưa nhận; hidden/8 GT do BTC giữ | Xin tài sản được phát; chưa nhận không phải đã đo FAIL hay PASS |
| B15 | MO.order_update chưa phân nhánh phí theo policy đơn cũ; schedule_callback chưa dùng giờ đặc biệt11/11 07:00–23:00 của lịch nghỉ | Ghi contract mismatch tài liệu/code, xin BTC chốt trước sửa implementation |

Nguồn policy bổ sung: [BH-01](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/policy/chinh-sach-bao-hanh.md>), [VC-03](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/policy/chinh-sach-van-chuyen-thanh-toan.md>), [QT](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/policy/quy-trinh-cod-hoan-hang.md>), [PB](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/policy/playbook-telesale.md>), [lịch nghỉ](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/policy/thong-bao-lich-nghi.md>), [policy cũ](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/policy/chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md>); mẫu ở [public_sample](</Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/test_set/public_sample>).

Các mục này là vấn đề dữ liệu/hợp đồng cần xác nhận, không phải lỗi Agent đã chứng minh. Không bỏ query/case khỏi official input để nâng điểm; nếu đã chạy thì giữ report thô kèm dispute. Phần tranh chấp ảnh hưởng quyết định release → INCOMPLETE và giữ candidate. Phần không bị ảnh hưởng vẫn có thể tiếp tục development/đo, không cần chờ tất cả mới bắt đầu.

## E4. Walkthrough các nhánh dễ chấm sai

Các dòng dưới là **kiểm tra logic của thiết kế**, không phải kết quả test runner đã chạy.

| Tình huống | Đường xử lý và kết luận cần có |
|---|---|
| Trace thiếu một turn hoặc trùng ID | B3 phát hiện; coverage chưa đủ, report chỉ chẩn đoán; không silent-drop |
| facts_used chứa đúng slot nhưng value sai khách | E có thể tính CCR; B4/B6 supplemental FAIL, không diễn giải CCR là memory đúng |
| Claim không có field GT | B4 unresolved + coverage; không tự tính đúng và không gán HR0 để đạt |
| order.create args đúng nhưng result.error | B5 báo tool execution FAIL dù assertion official có thể PASS |
| Handoff brief thiếu required field | B5 validate HB FAIL; consultant nói đúng sau đó không cứu lỗi Agent |
| Case có memory_expectation nhưng thiếu memory_writes | B3 INCOMPLETE; không chấp nhận memory_checks=[] làm PASS |
| Chung SĐT ghi nhầm customer_id | B6 FAIL có evidence state; không đưa fact cá nhân vào FAQ |
| Baseline RQR=0, full=0 | B7 relative reduction N/A; D7 review, không tự “giảm 40%” |
| Hard FAIL, judge PASS | C2 hybrid FAIL; official không bị sửa |
| Judge thiếu ID hoặc evidence không tồn tại | C2 retry1 lần để sửa format; còn lỗi INCOMPLETE |
| RAG chỉ trả59/60 qid | C3 coverage thiếu; E có thể cho số thô nhưng suite chưa hoàn tất |
| ASR thiếu hypothesis hoặc thiếu audio BTC | B8 báo IDs thiếu; phần nhóm/sample riêng; không gọi là đo đủ BTC |
| Diarization không có đoạn phủ midpoint | C4 tính sai speaker cho segment; không bỏ segment |
| Ba turn warm-up có lỗi chất lượng | B9 chỉ loại khỏi latency view; B4–B7 vẫn chấm lỗi |
| Simulator hết kiên nhẫn sớm | C5 kết thúc hợp lệ, ghi outcome/patience/ended_by; khác lỗi hạ tầng |
| Fixed-turn scenario có16 lượt | B2 chạy đúng input; không áp giới hạn12của simulator |
| Call thường không có lesson mới | D3 vẫn có QA/Reflection record no-change khi chọn M2; không sinh FAQ bắt buộc |
| Lỗi Frozen được viết lại thành Growth | D1/D4 giữ provenance; không gọi test độc lập |
| Chưa có active version | D6 chạy initial R0, giữ mốc kể cả chưa đạt threshold |
| Candidate sửa sau khi review/eval PASS | D5/D7 invalidate approval/report tương ứng, duyệt/đo lại |
| Growth đạt nhưng Frozen regression | D7 FAIL theo gate nhóm; giữ active, trả lỗi về proposal |
| M1 không làm voice/diarization | A2 ghi NOT_APPLICABLE từ đầu, không chặn M1 |
| M2 chưa có R2 | D6 chưa đủ chứng minh≥ 3 vòng; không đổi nhãn report R1 thành R2 |

Ví dụ nối xuyên suốt: consultant gặp gap “đổi size cho đơn cũ” → D2 tạo FAQ hướng dẫn tra ngày mua và policy đúng thời điểm → D4 gán expected tests độc lập cho đơn cũ/mới → D5 review → B/C chạy suite áp dụng trên cùng Frozen/Growth → D6 so phiên bản → D7 active đúng hash hoặc giữ candidate. Nếu phí đổi trả của mock chưa khớp policy cũ (B15), ghi tranh chấp thay vì tự chọn số để làm PASS.

## E5. Đối chiếu F01–F17 sau sửa thiết kế

| Fix của can_sua.md | Vị trí xử lý | Phần còn cần khi triển khai / chờ BTC |
|---|---|---|
| F01 Trace/coverage | A2, B2–B3 | Xây validator và chạy trace thật |
| F02 Extractor/CCR/HR | B4, B7 | Audit người, semantic checks; không lấy GT làm prediction |
| F03 Handoff/tool success | B5 | Validate HB và tool/state thực |
| F04 Memory/PII | B3, B6 | Snapshot/masking/TTL/delete tests |
| F05 GT tranh chấp | B1, D5, E3 | B01–B15 cần xác nhận tương ứng |
| F06 RAG | C3 | Retriever/answer judge và60 result thật; Q20/Q57 chưa chốt |
| F07 ASR/diarization | B8, C4 | Audio/segments chưa nhận; triển khai scoring views |
| F08 Latency/cost/voice | B9, C6 | Timestamp/usage/concurrency thật; B09 cần thống nhất warm-up |
| F09 A.6/Tool Accuracy | B9–B10, C6 | Report adapter, expected tool labels và chi phí đo được |
| F10 Simulator | C5 | Engine/rule tests/3 seed thật; định nghĩa độ lệch chờ BTC |
| F11 Reflection/R2 | D3, D6 | Record mỗi call, vòng cải tiến thật; không suy đã đạt từ sơ đồ |
| F12≥ 10 lỗi | B10, E4 | Casebook từ lỗi Agent thật |
| F13 Hard coverage | B1 | Điền case IDs trên dataset nhóm |
| F14 J01/selector | C1–C2, E1 | Nạp nguyên văn rubric, human agreement |
| F15 Inventory/nguồn | B1, E2–E3 | Cập nhật khi BTC phát tài sản mới |
| F16 Vai trò Gate/runner | A1, D1, C5 | Chính sách nhóm, không mô tả thành cấm đoán BTC |
| F17 R0/release/hash | A2, D5–D7 | Lifecycle và suite applicability thực |

**Nghiệm thu tài liệu:** flow và lời giải thích thống nhất; các nhánh thiếu/lỗi có đường xử lý; PNG/link mở được offline; số ô gốc được giữ; có nguồn cho ngưỡng và tách nhãn nhóm/BTC. Không tự chấm “10/10” hoặc tuyên bố đã chạy đạt.

Ba tài liệu audit được giữ làm mốc trước sửa: [can_sua.md](can_sua.md), [tổng quan đề/BTC](tong_quan_de_bai_va_btc.md), [phân công](phan_cong_btc_va_nhom.md). Lần này không triển khai runner, không sửa scorer/data/repo, không benchmark Agent, không xuất thêm HTML/PDF.
