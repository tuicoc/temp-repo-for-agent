# Luồng hoạt động và ý đồ thiết kế

[![version](https://img.shields.io/badge/version-0.0.0-blue.svg)](README.md)

Đọc kèm `diagrams.md`. Số mục khớp một một: mục 8 ở đây giải thích hình 8 ở đó. Hình 1 là toàn cảnh, dùng để soi chỗ thiếu và mở đầu buổi bảo vệ.

Bản này viết theo framework: mọi thứ trong đường nóng và đường nguội đều được mô tả bằng khái niệm của LangGraph (state, node, edge có điều kiện, subgraph, `Command`, `interrupt`, checkpointer) và của LangChain (`init_chat_model`, structured output, tool binding, LLM cache), tool nghiệp vụ đi qua MCP bằng `langchain-mcp-adapters`. Không có code, nhưng ai cầm tài liệu này lên là biết node nào tên gì, nhận gì, trả gì và thuộc ai.

Giả định đã chốt với bạn: khách là người dùng cuối, ngành hàng chưa quyết nên ontology có phần lõi dùng chung và phần thuộc tính theo ngành; 3 người, 4 tuần; LLM và embedding qua API; harness tự dựng bằng `StateGraph`; không dùng giao thức A2A, multi-agent theo Hướng 2; copilot dùng lại `AdvisorAgent`; cảnh báo là đầu ra của `PolicyAgent`; truy vết theo đề và hiện lại được cho QA, trace bằng Langfuse; setup thật để chạy được và deploy được; giữ hai nhịp nóng nguội; gộp QA với judge; có ma trận tài nguyên chia sẻ; có node nén ngữ cảnh.

---

## Sáu nguyên tắc chi phối mọi thứ

**Hai nhịp.** Đường nóng là những gì xảy ra khi khách đang chờ. Đường nguội chạy sau khi cúp máy, không ai chờ nên được phép chậm và dùng model to. Mọi việc nặng đều bị đẩy sang đường nguội. Quyết định này giải cùng lúc hai thứ vốn mâu thuẫn là độ trễ và chất lượng bộ nhớ.

**Công tắc thay vì nhánh code.** Bộ nhớ đi vào hệ thống qua đúng một node là `retrieve`. Tắt node đó là có baseline, cùng model cùng prompt cùng tool. Đề bắt baseline chỉ được khác ở việc có nạp bộ nhớ hay không, nên nếu viết hai đường code riêng thì không ai tin con số.

**Sự thật về khách nằm trong bộ nhớ, sự thật về doanh nghiệp nằm sau tool.** Giá không bao giờ là một fact hiện hành trong hồ sơ khách. Cái được lưu là sự kiện đã báo giá này, theo báo giá `quote_id` này, cho khách này, hôm đó. Muốn nói một con số thì phải vừa gọi tool trong lượt đó. Đây là chống bịa giá ở mức mô hình dữ liệu, trước cả guardrail.

**Tất định thì là code, phán đoán mới là agent.** Đọc bộ nhớ, dựng brief, cắt ngữ cảnh, quét regex đều ra cùng một kết quả mỗi lần nên chúng là node code thuần của harness. Chỉ có bốn chỗ cần phán đoán: định tuyến khi phải hiểu ý khách, soạn lời tư vấn, duyệt chính sách, và quyết định ghi gì vào bộ nhớ. Bốn chỗ đó là bốn agent, cộng agent chấm điểm ở đường nguội.

**M2 là cắm thêm, không sửa lõi.** Mọi hạng mục M2 là một node, một tool, một bảng hoặc một trang UI bật bằng feature flag. Tắt flag là còn nguyên M1 chạy được. Phụ lục A là bản đồ flag. Đây là câu trả lời cho yêu cầu của bạn: không kịp thì vẫn đủ M1, muốn phát triển thêm thì không phải đập.

**Không có số thì không có gì.** Mọi quyết định đều có một con số kiểm được đứng sau, và con số đó tái lập bằng một lệnh. Cache và manifest ở mục 17 và Phụ lục D là thứ biến câu này thành sự thật.

**Quy ước đặt tên.** Agent là danh từ có hậu tố Agent, tên lấy đúng bảng C.3 của đề. Node của graph là động từ chữ thường. Tool viết dấu chấm phân cấp. Bảng dữ liệu viết snake_case. Feature flag viết `ff.<tên>`.

Năm agent trong sản phẩm: `OrchestratorAgent`, `AdvisorAgent`, `MemoryAgent` (M1) và `PolicyAgent`, `QaAgent` (M2). Một agent chỉ sống trong bộ đánh giá: `SimulatorAgent` (M2). Không còn `JudgeAgent`: QaAgent là judge, đúng như đề định nghĩa "QA / Evaluator Agent chấm điểm cuộc gọi theo rubric". Không còn "Worker": những lời gọi model một phát là node bên trong subgraph của agent sở hữu chúng.

---

## 1. Toàn cảnh · hình 1

Kể bằng đúng ca của đề, nhưng lần này ghi rõ node và service.

**Ngày 12 tháng 3, cuộc 1.** Chị Hoa gọi hotline. Ở M1 cuộc gọi tồn tại dưới dạng file ghi âm nạp theo lô, hoặc là một phiên chat. File đi qua **L0** (pipeline `ingest`, ngoài graph): nhận dạng giọng nói, ITN đưa "bốn triệu tám trăm chín mươi" về 4.890.000, che PII thành token. Phiên chat thì đi thẳng vào node `perceive` của graph nóng.

Node `resolve` tra số, chưa gặp nên tạo `customer_id` mới với tier UNKNOWN. `retrieve` không có gì để nạp. `route` chọn lane NEW. `AdvisorAgent` tư vấn, gọi `catalog.search` rồi `pricing.get_quote`, tool trả về `quote_id Q-1071`, giá 4.890.000, khuyến mãi hết hạn 16 tháng 3. Chị nói "để hỏi ông xã". Advisor gọi `schedule.callback`. `guard_hard` xác nhận con số 4.890.000 trong câu trả lời nằm trong tập giá tool vừa trả. `respond` phát ra.

**Cúp máy.** API ghi một job vào bảng `jobs`. Worker nhặt job, chạy graph nguội của **`MemoryAgent`**: `extract` tách ứng viên, `gate` quyết định ghi gì (phòng 25 m², có con nhỏ, ngân sách 5 triệu, đã tư vấn SKU-AP-X theo Q-1071, rào cản chờ hỏi chồng, kết quả hẹn gọi lại), `commit` ghi vào sổ cái với nguồn gốc là cuộc gọi nào lượt nào, `summarize` viết một dòng episodic. Ở M2, worker chạy tiếp graph của `QaAgent` để chấm cuộc gọi theo rubric và, nếu cuộc đáng học, viết một bài học có cấu trúc chờ duyệt.

**Ngày 14 tháng 3, cuộc 2.** Chị gọi lại. `resolve` khớp số, tier VERIFIED. `retrieve` đọc sổ cái qua `mcp-memory` và gọi hàm `render_brief` (hàm thuần thuộc module của MemoryAgent) ra một Call Brief có đánh số dòng. `refresh` gọi song song `pricing.get_quote(Q-1071)` và `inventory.check`, tool bảo báo giá còn hạn, còn hàng. `route` thấy VERIFIED, có brief, có rào cản tồn đọng, chọn lane CONTINUITY mà không cần gọi model. `budget` xếp ngữ cảnh theo thứ tự ưu tiên. Advisor mở đầu bằng xác nhận tiếp nối, không hỏi lại gì. Chị đồng ý, Advisor gọi `order.create(quote_id=Q-1071)`, server tự áp đúng giá đã cam kết. Guard qua. Chốt đơn. Cúp máy, đường nguội lại chạy, ghi thêm fact đơn hàng.

**Giả sử giữa cuộc 2 chị hỏi "đang cho con bú dùng được không".** `route` không tìm thấy gì trong khối FAQ, đặt lane OUT_OF_SCOPE và ghi tín hiệu `oos_early`. Advisor thừa nhận không có thông tin trước, rồi đề nghị kết nối người phụ trách. Nếu chị đồng ý, `handoff` dựng Handoff Brief, chuyển `mode` sang copilot và dừng bằng `interrupt` chờ nhân viên nhận máy. Nhân viên nhận, nói chuyện tiếp trong cùng thread, mỗi câu nhân viên gõ đi qua guard để cảnh báo trước khi gửi. Cúp máy, đường nguội vẫn chạy trên toàn bộ transcript, kể cả phần người nói.

**Cuối tuần, nhịp học.** Job `collect` gom các tín hiệu ngoài phạm vi từ kho hội thoại và từ các lượt chạy simulator, gom cụm, đẩy vào bảng `proposals`. Người duyệt mở trang Cải tiến, bấm duyệt. Job `apply` sinh khối FAQ phiên bản mới và thêm ca test vào growth set. Chạy lại golden set. Bảng số vòng 1 đặt cạnh vòng 0.

**Song song, nhịp đo.** `eval run` chạy cả hai cuộc của kịch bản này qua chính graph nóng, hai lần, một lần `memory=on` một lần `memory=off`, cùng cache cùng manifest, in ra bảng so sánh. Lần tắt bộ nhớ sẽ hỏi lại diện tích phòng, ngân sách, có con nhỏ, và không có `quote_id` để giữ giá.

Ba nhịp có ba chu kỳ: hội thoại theo lượt, ghi nhớ theo cuộc gọi, học theo tuần. Vì chu kỳ khác nhau nên chúng tách rời được mà không cản nhau, và vì tách rời được nên baseline mới chỉ là một công tắc.

---

## 2. Kiến trúc triển khai · hình 2

*Nhận vào: yêu cầu chạy được trên laptop và deploy được. Trả ra: một `docker compose up` và một chế độ chạy một tiến trình cho M1.*

Bảy service, trong đó chỉ một cái là hạ tầng ngoài:

| Service | Việc | Công nghệ | Mức |
|---|---|---|---|
| `postgres` | Sổ cái, checkpointer, jobs, signals, proposals, KB (pgvector) | Postgres 16 + pgvector | M1 |
| `api` | Graph nóng, endpoint `/calls/start`, `/calls/{id}/turn` (SSE), `/calls/{id}/end`, `/copilot/resume`, `/handoff/accept` | FastAPI + LangGraph | M1 |
| `worker` | Graph nguội của MemoryAgent, graph của QaAgent, job collect/cluster/apply | Python vòng lặp poll bảng `jobs` | M1 |
| `mcp-memory` | Đọc và ghi sổ cái, phân quyền theo vai | FastMCP | M1 |
| `mcp-catalog` | Catalog, tồn kho, báo giá | FastMCP | M1 |
| `mcp-crm` | Khách, tạo đơn, hẹn gọi lại | FastMCP | M1 |
| `ui` | Chat, Agent Console, QA Review, Cải tiến, Dashboard, Bàn giao ca | Streamlit multipage | M1 |
| `mcp-order`, `mcp-knowledge` | Trạng thái đơn, RAG chính sách | FastMCP | M2 |
| `langfuse` | Trace | Cloud Hobby mặc định, self-host là profile tùy chọn | M1 |

**Vì sao FastAPI cộng Streamlit.** Bộ đánh giá và UI phải gọi cùng một graph, và graph phải chạy được ≥ 2 phiên đồng thời ở M2. Đặt graph sau một API là cách rẻ nhất để ba thứ (UI, eval runner, worker) dùng chung một thứ. Streamlit vì đề nói web đơn giản là đủ và nó là cách nhanh nhất để có sáu trang; giới hạn duy nhất là không bắt được sự kiện gõ phím, nên cảnh báo copilot xảy ra lúc bấm gửi chứ không phải lúc đang gõ, và điều đó chấp nhận được.

**Vì sao không Redis, không Celery.** Hàng đợi đường nguội là một bảng `jobs` với `SELECT ... FOR UPDATE SKIP LOCKED`. Ở quy mô này nó đủ, và ít hơn một container là ít hơn một thứ hỏng lúc demo.

**Chế độ M1 một tiến trình.** `make dev` chạy api và worker trong cùng tiến trình (worker là một task nền), MCP server chạy bằng transport stdio (api spawn subprocess), Streamlit gọi api ở localhost. Chỉ còn Postgres trong Docker. Cùng code, chỉ khác file cấu hình. `make up` mới bung đủ compose với MCP qua streamable-http.

**Langfuse.** Bản self-host v3 cần sáu container (web, worker, Postgres, ClickHouse, Redis, MinIO) và khoảng 8 GB RAM, quá nặng cho laptop demo. Langfuse Cloud gói Hobby miễn phí, 50 nghìn đơn vị mỗi tháng, giữ dữ liệu 30 ngày, 2 người dùng. Mặc định dùng Cloud; giữ một `docker-compose.langfuse.yml` để bật self-host khi có máy. Vì Hobby chỉ 30 ngày và 2 người dùng nên mọi metadata truy vết đều được lưu trong Postgres của mình (mục 16), Langfuse chỉ là màn hình soi, không phải nguồn sự thật.

---

## 3. Trạng thái phiên và ma trận tài nguyên · hình 3

*Nhận vào: câu hỏi "ai được đọc, ai được ghi cái gì". Trả ra: một bảng, và ba lớp thi hành để bảng đó không chỉ là lời hứa.*

### 3.1 `HotState`, trạng thái của graph nóng

Một `TypedDict` duy nhất, lưu bằng checkpointer Postgres theo `thread_id = call_id`. Mỗi lượt thoại là một lần `invoke` trên cùng thread, checkpointer khôi phục state nên working memory không cần bảng riêng.

| Trường | Nội dung | Node ghi | Node đọc |
|---|---|---|---|
| `call_id`, `channel`, `now` | Định danh cuộc gọi, kênh, đồng hồ ảo | api lúc start | mọi node |
| `mode` | `speak` hoặc `copilot` | api, `handoff` | `respond` |
| `switches` | `memory`, `exemplars`, `faq_version`, `playbook` | api, eval runner | `retrieve`, `budget` |
| `customer_id`, `tier`, `keys_seen` | Kết quả nhận diện | `resolve` | `route`, `retrieve`, guard |
| `messages` | Lịch sử lượt thoại, reducer `add_messages` | `perceive`, `respond`, `human_send`, tools | Advisor, `compact` |
| `working_summary` | Tóm tắt các lượt cũ trong cuộc gọi này | `compact` | Advisor, `budget` |
| `brief` | Call Brief: text và `lines[{id, fact_ids, text}]` | `retrieve` | `budget`, Advisor, `handoff` |
| `freshness` | Cảnh báo lệch tươi mới | `refresh` | `route`, `budget` |
| `lane`, `intent`, `oos_early` | Quyết định định tuyến | `route` (Orchestrator) | Advisor, `budget`, `respond` |
| `context_pack` | Phần ngữ cảnh đã chọn, token đã dùng, phần bị cắt | `budget` | Advisor |
| `tool_results` | Kết quả tool của lượt này: `quote_id`, giá, tồn kho, mã đơn | Advisor (node tools) | guard, Policy, `respond` |
| `draft` | `{text, used_brief_lines, confidence}` | Advisor | guard, Policy, `respond` |
| `regen_count`, `block_reasons` | Số lần sinh lại và lý do chặn | guard, Policy | Advisor |
| `guard` | Kết quả `hard` và `soft` | `guard_hard`, Policy | `respond`, UI |
| `flags` | `tool_error`, `asr_low_conf`, `format_error`, `handoff_requested`, `oos_late`, `tool_health` | nhiều node | `route` |
| `reply` | Câu đã phát, `ttft`, `ttft_content` | `respond` | api, eval |
| `handoff_brief` | Bản bàn giao | `handoff` | UI |
| `suggestion`, `human_decision` | Gợi ý copilot và quyết định của người | `respond`, `human_send` | UI, signals |
| `trace` | `turn_id`, `langfuse_trace_id` | `perceive` | mọi node |

### 3.2 Chiếu state cho từng agent

Subgraph trong LangGraph khai báo schema đầu vào riêng. Agent chỉ nhận đúng lát cắt được khai báo, không phải nhận cả state rồi hứa không đọc.

| Agent hoặc node | Được nhận | Được ghi trả về |
|---|---|---|
| `OrchestratorAgent` (`route`) | `tier`, `brief` có hay không, câu khách vừa nói, `freshness`, `flags`, `switches` | `lane`, `intent`, `oos_early`, `Command(goto)` |
| `AdvisorAgent` | `messages`, `working_summary`, `brief`, `freshness`, `context_pack`, `lane`, `tier`, `tool_results`, `block_reasons`, `now`, `mode` | `draft`, `tool_results`, `flags.oos_late` |
| `guard_hard` | `draft`, `tool_results`, `tier`, `customer_id` | `guard.hard`, `block_reasons`, `regen_count` |
| `PolicyAgent` (`guard_soft`) | `draft`, `tool_results`, `tier`, `policy_snippets`, `now`. **Không** nhận `brief`, **không** nhận `messages` | `guard.soft`, `block_reasons` |
| `MemoryAgent` (graph nguội, state riêng `ColdState`) | `call_id`, `customer_id`, transcript đã tokenize, fact hiện hành, `now` | ghi sổ cái qua vai `memory_writer` |
| `QaAgent` (graph nguội) | transcript, tool log, rubric, ground truth nếu là eval | `scores`, `lesson` đề xuất, `signals` |

Policy nhận ít hơn Advisor là cố ý, lý do ở mục 20.

### 3.3 Ma trận tài nguyên chia sẻ

R là đọc, W là ghi, dấu gạch là không chạm.

| Tài nguyên | Harness (code) | Orchestrator | Advisor | Policy | Memory (nguội) | QA (nguội) | Job collect/apply | Người (UI) | Eval runner |
|---|---|---|---|---|---|---|---|---|---|
| `HotState` + checkpointer | R/W | R/W lát cắt | R/W lát cắt | R/W lát cắt | – | – | – | W qua copilot | R |
| `raw_transcripts` | W (append) | – | – | – | R | R | – | R | R |
| `facts`, `episodes` (sổ cái) | R (prefetch) | – | R (tool `memory.*` chỉ đọc) | – | **W duy nhất** | R | – | R | R |
| `identities` | R + W tạm (provisional) | – | – | – | W xác nhận | – | – | R | R |
| `pii_vault` | W (L0), R (detokenize, chỉ khách đang nói) | – | – | – | – | – | – | W xóa (M2, admin) | – |
| `quotes`, `orders`, `callbacks` (CRM) | R (`refresh`) | – | R/W qua tool | R (`tool_results`) | R | R | – | R | R (assertion) |
| `catalog`, `inventory` | R (`refresh`) | – | R qua tool | – | – | – | – | R | R (ground truth) |
| `kb_chunks` (M2) | – | R (phát hiện OOS) | R qua tool | R (policy snippets) | – | – | W sau duyệt | R | R (Recall@k) |
| `faq_block` (text, có version) | R (`budget`) | R | R (trong prompt) | – | – | – | W version mới sau duyệt | duyệt | R (ghi version vào manifest) |
| `exemplars` (M2) | R (`retrieve`) | – | R (trong prompt) | – | – | – | W sau `policy_clean` + duyệt | duyệt | R |
| `playbook` (M2) | R (`retrieve`) | – | R | – | – | W đề xuất | W áp dụng / thu hồi | duyệt | R |
| `signals` | W | W (`oos_early`) | W (`oos_late`) | W (vi phạm) | – | W (điểm) | R | W (👍/👎) | W (ca sai) |
| `proposals` | – | – | – | – | – | W | R/W | R/W trạng thái | – |
| `handoffs` | W | – | – | – | – | – | – | R/W nhận máy | – |
| `jobs` | W (enqueue lúc cúp) | – | – | – | R/W | R/W | R/W | – | W đồng bộ |
| LLM cache | – | – | – | – | – | – | – | – | R/W (chỉ khi eval) |
| Langfuse | W trace | W | W | W | W | W | W | R link | W dataset run |

### 3.4 Ba lớp thi hành

1. **Schema subgraph.** Policy không có trường `brief` trong input schema thì về mặt kỹ thuật không đọc được.
2. **Vai của MCP client.** Ba `MultiServerMCPClient` cấu hình khác nhau: `advisor` (tool nghiệp vụ + `memory.*` đọc), `harness` (`memory.*` đọc, `identity.*`), `memory_writer` (`memory.commit_*`). Tool ghi không nằm trong danh sách tool bind cho Advisor, và server kiểm tra header vai, sai vai trả 403.
3. **Vai Postgres.** `app_hot` không có INSERT/UPDATE trên `facts` và `episodes`; `app_cold` có. Ba dòng SQL, nhưng khi bị hỏi "làm sao chắc Advisor không ghi bộ nhớ", câu trả lời là "nó không có quyền ở cả ba tầng".

Ngoại lệ duy nhất được ghi thành văn: đường nóng ghi tạm vào `identities` khi khách tự khai số hoặc mã đơn giữa chat. Đó là con trỏ, không phải fact, và nó ở trạng thái provisional cho tới khi MemoryAgent xác nhận ở đường nguội.

---

## 4. L0 tiếp nhận · hình 4

*Nhận vào: file ghi âm theo lô, hoặc một câu chat. Trả ra: một `NormalizedUtterance` gồm text đã chuẩn hóa, kênh, độ tin cậy từng đoạn, và ánh xạ token PII.*

L0 có hai nửa sống ở hai chỗ khác nhau, và đó là quyết định đầu tiên.

**Nửa audio là pipeline offline `ingest`, không nằm trong graph.** Đề nói rõ M1 là chat text cộng xử lý file ghi âm offline. Nên audio đi qua một script theo lô: `audio intake` (Silero VAD cắt khoảng lặng) → `asr` (faster-whisper hoặc PhoWhisper, chạy local, kèm độ tin cậy từng đoạn) → `transcript repair` (M2, `ff.audio_repair`: từ điển tên sản phẩm "Xiao Mi" → Xiaomi, "sai z eo" → size L; diarization bằng pyannote; audio nhiễu) → nhập chung vào ba bước chuẩn hóa. Đầu ra là các lượt thoại đã có `speaker` và `asr_confidence`, được ghi vào `raw_transcripts`, rồi được nạp vào graph nóng như thể khách đang chat, từng lượt một. Cách này làm cho một cuộc gọi ghi âm và một phiên chat đi qua đúng một harness, và đó là điều kiện để WER đi chung bảng với bốn chỉ số kia.

**Nửa text nằm trong node `perceive` của graph nóng**, chạy dưới 50 ms: `text cleanup` (teencode, viết tắt, không dấu, pha Việt Anh: "sp nay co ship cod k a"), rồi ba bước chuẩn hóa chung.

Ba bước chung, cùng một module cho cả hai nửa, vì nếu tách đôi thì hai bản chuẩn hóa số sẽ lệch nhau sau hai tuần, mà chuẩn hóa số chính là chỗ tính Entity Accuracy:

**`diacritic normalizer`** đưa dấu tiếng Việt về NFC, chạy trước mọi so khớp chuỗi.

**`inverse text normalizer`** chuyển dạng nói sang dạng viết cho tiền, số điện thoại, ngày hẹn gọi lại. Đây là chỗ ăn điểm khác biệt nhất của cả tầng vì Phụ lục A.5 nói thẳng Entity Accuracy quan trọng hơn WER. Viết bằng luật cộng một test suite riêng: "bốn triệu tám" là 4.800.000 chứ không phải 4.000.008, "hai trăm bốn chín k" là 249.000, "một củ hai" là 1.200.000, "bốn tám chín" có thể là dãy chữ số, "thứ tư tuần sau" phải quy ra ngày theo đồng hồ ảo `now`. Có ngày trong `now` là bắt buộc, vì bộ đánh giá chạy kịch bản có `days_later` và không được đọc giờ hệ thống.

**`PII tokenizer`** che thông tin cá nhân theo cách khôi phục được. M1 chỉ cần regex và che một chiều khi ghi log; M2 (`ff.pii_vault`) thay bằng token `<PHONE_1>`, `<ADDR_1>` lưu trong `pii_vault` kèm `customer_id`, để nghiệp vụ vẫn dùng được và xóa toàn bộ dữ liệu một khách chỉ là xóa dòng trong vault. Node `detokenize` ở cuối mục 11 là đường khôi phục, và nó chỉ khôi phục token của chính khách đang nói chuyện.

**Bộ đo ASR** (`asr_eval`, ≥ 20 file) đi kèm L0 chứ không phải L5: mỗi file có transcript chuẩn và danh sách thực thể tiền, số điện thoại. Runner của mục 17 chỉ gọi hàm `score_asr()` và in vào chung bảng. Chuẩn hóa trước khi tính WER là chuyển thường, bỏ dấu câu, chuẩn hóa số bằng đúng ITN ở trên; báo cáo phải nêu rõ ba bước này và tách theo hai miền giọng, vì cùng một hệ thống mà chuẩn hóa khác nhau có thể lệch WER 5 tới 10 điểm.

---

## 5. L1 danh tính · hình 5

*Nhận vào: câu đã chuẩn hóa cộng siêu dữ liệu kết nối (số gọi đến, kênh, handle). Trả ra: `customer_id` và `tier`. Tier được dùng lại ở `route` và ở guard.*

Node `resolve` là code thuần, chạy lúc bắt đầu cuộc gọi và chạy lại khi trong lượt thoại xuất hiện khóa mới (khách đọc số, nhắc mã đơn).

**`extract keys`** tách khóa từ siêu dữ liệu và từ nội dung: số điện thoại, mã đơn, handle Zalo hoặc Facebook.

**`phone path`** chuẩn hóa số, băm có khóa bí mật (HMAC), tra bảng `identities`. Băm có khóa vì không gian số điện thoại Việt Nam chỉ mười chữ số nên băm trơn tra ngược trong vài giây. Giữ bốn số cuối để hiển thị.

**`channel path`** vẽ nét đứt vì là phần giả định: không có cách tự động nối handle Facebook với số điện thoại. Zalo OA có cơ chế khách chia sẻ số nên đường Zalo có thể là tự động; Facebook thì liên kết chỉ xảy ra khi khách tự khai số hoặc nhắc mã đơn. Hệ quả lên dataset phải nói với người sinh dữ liệu từ tuần một: mười khách đa kênh bắt buộc ở M1 phải có một khoảnh khắc khách gõ số hoặc mã đơn trong chat.

**`bind identity`** trỏ dòng định danh về một `customer_id`. Chỉ sửa con trỏ, không đụng fact. Mọi fact giữ nguyên kênh và định danh nguồn, nên gộp nhầm vẫn tách ra được (chưa có nút tách, nhưng dữ liệu không chặn). `customer_id` không phải số điện thoại: vì PII, vì người ta đổi số, và vì cần một lớp gián tiếp cho việc gộp.

**`confidence tier`** quyết định phần sau được phép nói gì:

| Tier | Điều kiện | Được làm gì |
|---|---|---|
| VERIFIED | khớp chính xác số gọi đến, hoặc khóa đã được MemoryAgent xác nhận | nạp brief đầy đủ, mở đầu bằng xác nhận tiếp nối, được đọc giá và mã đơn |
| PROBABLE | khách tự khai số hoặc mã đơn giữa chat, chưa xác nhận chéo | brief vẫn nạp vào ngữ cảnh nhưng lane là CONFIRM_IDENTITY: chỉ hỏi câu xác nhận, cấm đọc giá, địa chỉ, mã đơn |
| UNKNOWN | không có khóa khớp | không nạp gì, lane NEW |

**Khách gọi từ số lạ (M2, `ff.unknown_number`)** đi đúng đường PROBABLE: khách nói "hôm trước bên em tư vấn chị máy lọc X", Advisor hỏi "chị cho em xin số điện thoại hôm trước liên hệ để em xem lại ạ", khách đọc số, `resolve` chạy lại, ghi provisional, tier PROBABLE, Advisor hỏi một câu xác nhận về thứ đã tư vấn, khách gật thì lượt sau được nâng VERIFIED trong cuộc gọi đó, và MemoryAgent ghi xác nhận liên kết ở đường nguội. Ràng buộc này không làm hỏng chỉ số vì Phụ lục A.1 quy định câu xác nhận không tính là câu hỏi thừa; làm ngược lại, tức số lạ mà đọc vanh vách hồ sơ để cày Context Carryover, là lỗi bảo mật và giám khảo sẽ hỏi đúng chỗ đó.

Hòa giải mâu thuẫn giữa kênh không thuộc tầng này. Việc của L1 chỉ là đảm bảo giá 690k từ Fanpage và 790k từ hotline cùng rơi vào một `customer_id`. Ai thắng là việc của mục 7.

---

## 6. L2 sổ cái, nhánh đọc · hình 6

*Nhận vào: `customer_id` từ L1. Trả ra: `brief` và `freshness` cho graph nóng, trong ngân sách 5 giây M1 và 3 giây M2.*

### 6.1 Ontology: lõi dùng chung và thuộc tính theo ngành

Vì ngành hàng chưa quyết, ontology có hai vùng và một cấu hình.

**Slot đóng lõi**, không phụ thuộc ngành, là tất cả những gì bộ chấm tham chiếu bằng tên: `budget_vnd`, `product_advised` (SKU), `variant` (size, màu), `quote` (`quote_id`, giá, khuyến mãi, hạn), `blocker` (chờ hỏi người nhà, so giá, chưa đủ tiền), `decision_maker`, `callback_at`, `outcome` (chốt, hẹn lại, từ chối), `order_ref`, `address_token`. M2 thêm `objection_type`, `objection_handling`, `sentiment`, `commitments` (cam kết đã hứa với khách).

**Thuộc tính nhu cầu theo ngành** nằm trong một slot đóng có schema cắm được: `need_attrs`, ví dụ máy lọc không khí có `room_area_m2`, `has_children`; giày có `foot_size`, `usage`. Mỗi ngành là một file schema; `must_not_ask` và `must_carry_over` trong file test gọi `need_attrs.room_area_m2`. Thêm ngành hàng là thêm một file schema cộng catalog, không đụng code sổ cái. Đây là câu trả lời cho tiêu chí 7 về thêm ngành hàng.

**Ghi chú mở** cho sự thật bền không thuộc slot nào (mua cho mẹ bị tiểu đường, lo tương tác thuốc). Có trần cứng theo khách, đầy thì từ chối và ghi log. Ghi chú mở không bao giờ là căn cứ cho một khẳng định về giá hay chính sách. Vùng này dễ chứa thông tin sức khỏe nên phải nêu trong phần PII của báo cáo.

### 6.2 Bảng dữ liệu

| Bảng | Cột chính | Tầng ký ức của đề |
|---|---|---|
| `facts` | `fact_id`, `customer_id`, `slot`, `value` (json), `kind` (preference, business_event, past_event, open_note), `status` (active, invalidated, disputed), `valid_from`, `valid_to`, `ttl_policy`, `confidence`, `source{call_id, turn_id, channel, extractor_version}`, `superseded_by` | Profile |
| `episodes` | `episode_id`, `customer_id`, `call_id`, `channel`, `started_at`, `summary`, `outcome`, `objection_type` (M2), `sentiment` (M2), `commitments` (M2), `source_turn_span` | Episodic |
| checkpointer LangGraph | state theo `thread_id` | Working |
| `kb_chunks` (M2) | `chunk_id`, `doc`, `section`, `text`, `embedding`, `version` | Semantic / KB |
| `faq_block` | `version`, `text`, `approved_by`, `created_at` | Semantic thu nhỏ ở M1 |
| `exemplars` (M2), `playbook` (M2) | xem mục 18 | Playbook (điểm thưởng) |

Sổ cái không xóa không ghi đè: đổi ý thì dòng cũ đóng cửa sổ hiệu lực, dòng mới mở ra. Khung nhìn `current_facts` chỉ trả về dòng `active` mà `valid_to` chưa qua theo đồng hồ ảo `now`. Chính khung nhìn này đảm bảo không bao giờ có hai giá trị mâu thuẫn cùng sống, đúng yêu cầu M1.

**TTL (M2, `ff.ttl_decay`)** là một cột chính sách theo slot: `quote` hết hạn theo `valid_until` của tool; `blocker` và ý định mua hết hạn sau 30 ngày; `address_token` sau 180 ngày thì hỏi lại là hợp lý; `need_attrs` không hết hạn. Hết hạn thì `current_facts` không trả về, và câu hỏi về slot đó không bị tính là thừa theo đúng quy tắc TTL của Phụ lục A.1.

### 6.3 Node `retrieve` và hàm `render_brief`

`retrieve` là công tắc bộ nhớ. `switches.memory=off` thì node trả về `brief=None` và không gọi gì; mọi thứ sau đó chạy như khách mới. Đó là baseline.

Khi bật, `retrieve` gọi `memory.get_profile`, `memory.get_episodes(n=3)`, `memory.get_open_items` qua vai `harness`, rồi gọi `render_brief(facts, episodes, now)`. Hàm này là **hàm thuần thuộc module `agents/memory/`**, render theo template, không để model viết tự do, nên nó rẻ (một tới hai giây kể cả gọi MCP) và tất định. Về sở hữu code, `MemoryAgent` vẫn là bên dựng Call Brief đúng như bảng C.3 của đề; chỉ là không tốn lượt gọi model. Điều này phải nói thành lời trên slide.

Brief có cấu trúc dòng đánh số `B1..Bn`, mỗi dòng mang `fact_ids`. Đây là cái giá rất rẻ để mục 16 truy vết được câu agent nói về đúng fact nào: Advisor trả `used_brief_lines`.

Nội dung brief theo đúng thứ tự đề liệt kê: khách là ai, đã gọi mấy lần và qua kênh nào; sản phẩm đã tư vấn kèm `quote_id`, giá, khuyến mãi, hạn; rào cản còn tồn đọng; fact đang tranh chấp; cam kết đã hứa (M2); hành động đề xuất tiếp theo (rút từ `blocker` và `callback_at`).

Ở M1 hàm chạy tại chỗ lúc bắt máy vì ngưỡng 5 giây không chặt. Nếu đo p95 vượt 3 giây ở M2, chỉ đổi chỗ gọi sang đường nguội (dựng sẵn sau `summarize`) và cache theo `customer_id`, không viết lại. Khi đó dựng sẵn là một cải tiến có số liệu chống lưng.

### 6.4 Node `refresh`, kiểm tra tươi mới

Hỏi lại tool xem những thứ brief trích dẫn còn đúng không: từng `quote_id` (`pricing.get_quote`), từng SKU (`inventory.check`), từng `order_ref` (`order.status`, M2). **Chạy song song bằng `asyncio.gather`** trên các tool MCP; ba báo giá cộng hai SKU cộng một đơn là sáu lời gọi, tuần tự thì hết sạch ngân sách, song song thì bằng lời gọi chậm nhất, dưới 800 ms. Cái nào lệch thì ghi một dòng vào `freshness.warnings`, ví dụ "Q-1071 đã hết hạn 16/03, giá hiện tại 5.200.000, KM mới GIFT-2". Dòng này không bao giờ bị `budget` cắt.

Node này giải yêu cầu M2 "phát hiện khuyến mãi hết hạn, hàng đã hết, không báo lại giá cũ" gần như miễn phí, và nó phải có từ M1 vì ca "khách đòi áp khuyến mãi đã hết hạn" nằm trong năm ca khó bắt buộc của M1.

---

## 7. L2 cổng ghi, graph nguội của `MemoryAgent` · hình 7

*Nhận vào: một job `persist` với `call_id`. Trả ra: các dòng mới trong `facts`, một dòng `episodes`, và (M2) một job cho `QaAgent`.*

Đây là graph LangGraph thứ hai, state riêng `ColdState`, chạy trong `worker`, dùng client MCP vai `memory_writer`. Nó là **đường duy nhất có quyền ghi sổ cái**.

**`load`** đọc `raw_transcripts` của cuộc gọi (đã tokenize), `current_facts` của khách, và `now`.

**`extract`** là một lời gọi model có structured output: danh sách ứng viên `{slot | note, value, kind, turn_id, span, confidence}`. M2 thêm `objection_type`, `objection_handling`, `sentiment`, `commitments` vào cùng lời gọi. Prompt nhận ontology của ngành (file schema ở 6.1) để không bịa slot. Chạy trên transcript đã tokenize nên PII không ra ngoài.

**`gate`** là bốn cửa xếp rẻ trước đắt sau, và nó chính là câu trả lời cho "ghi gì, không ghi gì":

1. `{classify}` ba nhánh: nhiễu và xã giao thì bỏ; ghi chú mở; slot đóng.
2. `{under cap?}` cho vùng mở: trần cứng, đầy thì từ chối và ghi log.
3. `{valid format?}` kiểm kiểu và khoảng hợp lý (ngân sách không phải 5 đồng, diện tích không phải 2500 m²). Trượt thì loại và ghi log.
4. `{wins by slot category?}`: không có một thang tin cậy duy nhất, vì với sở thích thì khách là nguồn đúng nhất còn với dữ kiện kinh doanh thì tool mới đúng.

| Loại slot | Ai thắng | Ví dụ |
|---|---|---|
| sở thích, nhu cầu | khách thắng tuyệt đối, lời mới thắng lời cũ | "thôi anh lấy màu trắng": dòng đen `invalidated`, dòng trắng `active` |
| dữ kiện kinh doanh | tool thắng tuyệt đối, lời khách chỉ lưu như một phát ngôn | khách bảo hôm trước báo 4 triệu, bản ghi `quote` là 4.890.000 |
| sự kiện đã xảy ra | bản ghi hệ thống thắng, không ai sửa lịch sử | đơn đã tạo lúc nào, ai báo giá |

**`{disputed}`** dành cho khách nói ngược dữ kiện kinh doanh. Không ghi đè, không cãi: đánh dấu `disputed`, brief lần sau nổi nó thành việc cần làm rõ, Advisor xử lý bằng câu xác nhận. Đây là lớp chống đầu độc thứ hai (M2, `ff.anti_poison` chỉ thêm việc: một fact bị hai nguồn độc lập phủ nhận thì tự chuyển `disputed` và thu hồi cả cụm cùng `source`). Lớp thứ nhất là quyền ghi ở mục 3.

**`commit`** là bước duy nhất trong cổng có thể cần model, và dùng model nhỏ: với mỗi ứng viên đã qua cửa, quyết `add`, `update`, `invalidate`, `skip` so với fact hiện hành, rồi gọi `memory.commit_facts`. Mỗi dòng mang nguồn gốc, cửa sổ hiệu lực, mức tin cậy. Nếu khóa danh tính provisional của cuộc gọi này được nội dung cuộc gọi xác nhận thì gọi `memory.confirm_identity`.

**`summarize`** viết một dòng episodic đúng mẫu của đề: "Cuộc 1 (12/03, hotline): tư vấn SKU-AP-X theo Q-1071 4.89tr, khách hẹn hỏi chồng, callback 14/03". Ghi `source_turn_span`.

**`enqueue_qa`** (M2, `ff.qa_agent`) tạo job cho graph của QaAgent (mục 17.6 và 18.3).

Bài toán mà mục này giải trực tiếp: một câu khách nói đùa ("anh mua cho công ty năm trăm người") đi qua một model khác, ở một nhịp khác, với luật ưu tiên và trạng thái tranh chấp, và không bao giờ được ghi bởi thứ đang chịu áp lực hội thoại.

---

## 8. L3 vòng lặp harness, graph nóng · hình 8

*Nhận vào: một lượt thoại của khách (hoặc một lượt transcript). Trả ra: một câu trả lời, các trường state đã cập nhật, và tín hiệu mở đường nguội khi cúp máy.*

### 8.1 Danh sách node và cạnh

Một `StateGraph(HotState)`. Node code thuần in thường không có tên agent; node thuộc agent ghi tên agent trong ngoặc.

| Node | Loại | Việc |
|---|---|---|
| `perceive` | code | chuẩn hóa text (mục 4), gán `turn_id`, mở trace Langfuse, đặt `flags.asr_low_conf` nếu lượt đến từ audio có độ tin cậy thấp |
| `resolve` | code | mục 5, chạy khi bắt đầu cuộc gọi hoặc khi xuất hiện khóa mới |
| `retrieve` | code, **công tắc memory** | mục 6.3, chỉ khi bắt đầu cuộc gọi; nạp thêm exemplar và playbook nếu `switches.exemplars` (M2) |
| `refresh` | code | mục 6.4, chỉ khi bắt đầu cuộc gọi |
| `compact` | code + một lời gọi model nhỏ | khi `messages` vượt ngưỡng token: tóm tắt các lượt cũ trừ bốn lượt cuối vào `working_summary`, xóa message cũ bằng `RemoveMessage`, giữ nguyên `tool_results` lượt này. Đây là mẫu "summarize conversation" chuẩn của LangGraph |
| `route` | `OrchestratorAgent` | mục 9, trả `Command(goto="budget" \| "handoff", update={lane, intent})`; `budget` luôn đứng ngay trước `advisor` |
| `budget` | code | xếp ngữ cảnh theo thứ tự ưu tiên vào `context_pack` trong hạn mức token của model; cắt từ dưới lên |
| `advisor` | subgraph `AdvisorAgent` | mục 10, trả `draft` và `tool_results` |
| `guard_hard` | code | mục 11 |
| `guard_soft` | `PolicyAgent` (M2, `ff.policy_agent`) | mục 11 |
| `safe_default` | code | câu an toàn theo lane khi hết trần sinh lại |
| `respond` | code | phát câu trả lời theo `mode`; ở copilot thì `interrupt` (mục 14); ghi `messages`, đo `ttft`, `ttft_content` |
| `handoff` | code | mục 13 |
| `human_send` | code | mục 14, chỉ chạy khi resume từ copilot |

Cạnh có điều kiện:

- `START → perceive → {đầu cuộc gọi?}` → `resolve → retrieve → refresh → route`; ngược lại → `{cần compact?} → compact? → route`.
- `route → budget → advisor`, hoặc `route → handoff → respond`.
- `advisor → guard_hard → {pass?}` → `guard_soft` nếu bật, → `respond`.
- chặn và `regen_count < 2` → `advisor` (với `block_reasons`); chặn và hết trần → `safe_default → respond`.
- `respond → END`. Sự kiện cúp máy do api nhận, ghi job `persist`; đó là node `persist` của đề, nằm ngoài graph nóng vì nó không được chờ.

**Thứ tự ưu tiên của `budget`**, cắt từ dưới lên: quy tắc cứng và giọng điệu; `freshness.warnings`; chỉ dẫn theo lane; rào cản và fact tranh chấp; sản phẩm và báo giá đã báo; `need_attrs` và slot lõi; ghi chú mở; ba episode gần nhất; `working_summary`; khối FAQ (M1) hoặc top-k KB (M2); playbook (M2); exemplar (M2). Exemplar bị cắt đầu tiên, cảnh báo tươi mới không bao giờ bị cắt. Đề hỏi thẳng "đưa gì vào prompt và cắt gì" nên bảng này phải khai báo được trong một file cấu hình, không chìm trong prompt.

### 8.2 Hai công tắc

`switches.memory` điều khiển ký ức của chính khách này, dùng để so với baseline. `switches.exemplars` (và `playbook`) điều khiển tri thức liên khách học từ khách khác, dùng để so vòng 0 với vòng 1 và 2. Khi so với baseline thì exemplar bật ở cả hai bên, vì baseline đề định nghĩa là hệ thống coi mỗi cuộc gọi độc lập, không phải hệ thống ngu hơn về mọi mặt. Tắt cả hai cùng lúc là đo trộn hai biến.

### 8.3 Đồng hồ ảo

Mọi node đọc `state.now`, không đọc giờ hệ thống. Api đặt `now` bằng giờ thật; eval runner đặt theo `days_later` của kịch bản. Không có đồng hồ ảo thì ca khuyến mãi hết hạn không tái lập được, vì hôm nay chạy còn hạn, tuần sau chạy hết hạn.

### 8.4 Ngân sách độ trễ và câu đệm

Trong LangGraph, `plan` và `observe` của đề là **cùng một node model gọi 1 tới N lần**: lượt không cần tool là một lần gọi, lượt có tool là hai. Nên đường nóng tốn một tới hai lượt gọi model, không phải "ít nhất hai".

`guard_hard` cần câu hoàn chỉnh nên không stream được nội dung trước khi quét. Cách giải: khi node model của Advisor trả về tool call, node tools phát một sự kiện custom qua `get_stream_writer()` với câu đệm chọn theo loại tool ("Dạ chị chờ em một xíu, em kiểm tra tồn kho ngay ạ"), UI hiện ngay. Câu đệm **chỉ phát ở lượt có tool call**, vì trong chat mà lượt nào cũng "dạ để em kiểm tra" thì rất giả. Báo **hai số**: `ttft` tính tới câu đệm hoặc tới nội dung nếu không có tool, và `ttft_content` tính tới lúc guard cho qua. Số thứ hai mới nói lên trải nghiệm, và nói cả hai là cách trung thực duy nhất.

Ngân sách một lượt: `perceive` và `resolve` dưới 200 ms; `route` dưới 300 ms vì đa số là luật; `refresh` dưới 800 ms nhờ song song; model của Advisor hai tới ba giây mỗi lần gọi; `guard_hard` dưới 50 ms; `guard_soft` dưới một giây với model nhỏ. Tổng p95 dưới 8 giây ở lượt có một vòng tool. Số đo thật lấy từ `reply.ttft` và Langfuse.

### 8.5 Trần sinh lại

Tối đa hai lần sinh lại rồi rơi xuống `safe_default` và ghi log, nếu không một câu nháp liên tục vi phạm sẽ làm vòng lặp quay mãi. Đề hỏi thẳng về xử lý lỗi nên chỗ này sẽ bị hỏi.

---

## 9. `OrchestratorAgent`, node `route` · hình 9

*Nhận vào: lát cắt ở mục 3.2. Trả ra: `lane`, `intent`, `oos_early`, và `Command(goto=...)`.*

Orchestrator nhìn dữ liệu đã có trong tay rồi quyết luồng. Năm thứ nó cần (tier, có brief không, tool có đang lỗi không, freshness, pha cuộc gọi) đều có sẵn trong state nên **đa số lượt quyết bằng luật, không gọi model**. Chỉ khi luật cần biết ý khách thì gọi bộ phân loại intent: model nhỏ, structured output là một enum, `temperature=0`, có cache. Bộ này vốn bắt buộc ở M1 (trích xuất intent) nên router lai không tốn thêm gì.

| Thứ tự | Điều kiện | Lane | Advisor được bind tool nào |
|---|---|---|---|
| 1 | `flags.tool_health` hỏng liên tiếp, hoặc khách đòi gặp người, hoặc Policy chặn hai lần liên tiếp vì chính sách | HANDOFF | không |
| 2 | `flags.asr_low_conf` | CLARIFY | không |
| 3 | tier PROBABLE | CONFIRM_IDENTITY | không |
| 4 | intent ∈ {trạng thái đơn, đổi size, đổi địa chỉ} | ORDER_SERVICE (M2); ở M1 thì lane OUT_OF_SCOPE kèm ghi chú "thừa nhận rồi bàn giao" | `order.status`, `order.update`, `crm.get_customer` |
| 5 | intent là câu hỏi thông tin và không có gì khớp trong `faq_block` (M1) hoặc `kb.search` (M2) | OUT_OF_SCOPE, ghi `oos_early` | **không tool nào**, để assertion "không gọi tool" chấm được |
| 6 | tier VERIFIED và brief có rào cản hoặc báo giá còn hiệu lực | CONTINUITY | catalog, pricing, inventory, order.create, schedule.callback, memory.* đọc, kb.search (M2) |
| 7 | còn lại | NEW | như CONTINUITY |

Trả về bằng `Command(goto="budget", update={...})` (rồi `budget` nối thẳng sang `advisor`) hoặc `Command(goto="handoff", ...)`. Đây là cơ chế chuyển giao nhiệm vụ chuẩn của LangGraph, và nó là thứ chứng minh "agent chuyển giao nhiệm vụ cho nhau" chứ không phải chuỗi prompt gọi tuần tự rồi đặt tên cho oai.

Lợi ba mặt của router lai: rẻ, nhanh, tái lập được. Tái lập là điều kiện sống còn vì đề trừ nặng số liệu không tái lập bằng code.

---

## 10. `AdvisorAgent`, subgraph plan · act · observe · hình 10

*Nhận vào: lát cắt ở mục 3.2. Trả ra: `draft{text, used_brief_lines, confidence}`, `tool_results`, `flags.oos_late`.*

Subgraph theo mẫu ReAct của LangGraph: node `model` (bind tool theo lane) ↔ node `tools` (`ToolNode`) ↔ `model`, lặp tới khi model trả câu không có tool call, tối đa ba vòng tool mỗi lượt. Model dựng bằng `init_chat_model` để đổi provider bằng cấu hình. Tool lấy từ client MCP vai `advisor` qua `langchain-mcp-adapters`.

**Chính sách gọi tool** là một bảng khai báo, vì đề bắt trình bày được "khi nào cần gọi tool và khi nào không":

| Loại thông tin | Nguồn bắt buộc |
|---|---|
| giá, khuyến mãi, tồn kho, thời gian giao, trạng thái đơn | luôn tra tool trong lượt này |
| chính sách đổi trả, ship, bảo hành | khối FAQ (M1) hoặc `kb.search` (M2) |
| thứ đã có trong brief và còn hiệu lực | không tra, dùng brief |
| xã giao, câu hỏi làm rõ | không tra |

**Bố cục prompt** theo đúng thứ tự `context_pack` của mục 8.1, mở đầu bằng quy tắc cứng: chỉ nói con số vừa có trong `tool_results`; không bao giờ nhận là người thật; không biết thì nói không biết trước; nếu tier không phải VERIFIED thì không đọc giá, địa chỉ, mã đơn; giọng điệu telesale Việt (dạ, vâng, ạ; xưng hô theo tuổi và giới ước lượng, mặc định "anh/chị" và "em"). Mỗi lane có một đoạn chỉ dẫn riêng ngắn.

**Đầu ra là structured output** `{reply, used_brief_lines, confidence}`. `used_brief_lines` là cách rẻ nhất để truy vết câu nói về fact (mục 16). `confidence=low` cộng lane không phải OUT_OF_SCOPE thì đặt `flags.oos_late`: đây là nguồn phát hiện ngoài phạm vi thứ hai, muộn, từ chính Advisor.

**Ca ngoài phạm vi.** Đề mâu thuẫn bề mặt: Case 3 nói khách hỏi ngoài phạm vi thì chuyển máy, Phụ lục A.3 nói ca khó thành công là "không gọi tool và trả lời rằng mình không có thông tin". Hòa bằng thứ tự: **thừa nhận không biết trước, đề nghị chuyển người sau**. Lane OUT_OF_SCOPE không bind tool nên assertion "không gọi tool" đúng về mặt cơ học, và `success_if` của ca khó phải viết là "không gọi tool cộng có câu thừa nhận", đừng viết là "đã chuyển máy".

**Báo giá và giữ giá.** Advisor không bao giờ tự tính giá. Muốn nói giá là gọi `pricing.get_quote`; muốn chốt là gọi `order.create(quote_id)`. Nếu `quote_id` hết hạn thì tool trả lỗi `EXPIRED_QUOTE` kèm báo giá mới, Advisor phải nói thẳng khuyến mãi đã hết và báo giá hiện hành. Ca "khách đòi áp khuyến mãi hết hạn" vì thế thành tất định ở tầng tool, không phụ thuộc model có mềm lòng hay không.

---

## 11. Guardrail: `guard_hard`, `PolicyAgent` và bề mặt cảnh báo · hình 11

*Nhận vào: `draft` cộng `tool_results` của lượt này. Trả ra: cho qua, hoặc chặn kèm lý do để Advisor sinh lại.*

### 11.1 `guard_hard`, code thuần

Bốn kiểm tra đầu không cần model, và đó là điểm chính: phần lớn guardrail của bài này là regex.

| Kiểm tra | Cách làm | Khi trượt |
|---|---|---|
| giá và khuyến mãi từ tool | quét mọi chuỗi trông giống tiền theo cách viết Việt (4.890.000đ, 4tr890, 4,89 triệu, 4 triệu 890) và mã khuyến mãi; đối chiếu với tập giá và mã trong `tool_results` lượt này | chặn, lý do "số 5.200.000 không có trong tool" |
| lộ PII | số điện thoại 10 số, CCCD 12 số, chuỗi giống địa chỉ ở tier không phải VERIFIED | chặn |
| tier cho phép tiết lộ | cờ tier so với danh sách thông tin nhạy | chặn |
| nhận là người thật | khớp mẫu câu ("em là người thật", "em không phải máy") | chặn |
| định dạng | rỗng, quá dài, không phải tiếng Việt, còn token PII chưa khôi phục | chặn |

Khoảng ba mươi dòng regex, nhưng nó biến ngưỡng hallucination về giá ≤ 5% từ hy vọng thành đảm bảo, và nó demo được trực tiếp trên màn hình.

Thứ tự bắt buộc: quét PII **trước** khi khôi phục token. Node `detokenize` đứng sau mọi kiểm tra và chỉ whitelist token của chính `customer_id` đang nói chuyện.

### 11.2 `guard_soft`, `PolicyAgent` (M2, `ff.policy_agent`)

Model nhỏ, structured output `{pass, violations[{type, quote, reason, fix_hint}]}` với `type` ∈ {cam kết sai chính sách, tiết lộ sai tier, giọng điệu, hứa điều tool không xác nhận}. Đầu vào là lát cắt ở mục 3.2 cộng `policy_snippets` lấy từ `kb.search` theo nội dung `draft`. Chỉ bắt thứ regex không bắt được: "đổi trả thoải mái" trong khi chính sách là 7 ngày, "ship miễn phí" khi tool không nói.

Cứng trước mềm sau vì cứng rẻ, tất định và chặn được đa số; để model chạy trước là trả tiền và trả độ trễ cho việc regex đã làm xong.

### 11.3 Cảnh báo là bề mặt của Policy, không phải agent thứ sáu

Cùng một đầu ra `violations` được dùng ở ba chỗ:

- **Chế độ speak:** chặn và sinh lại. Agent Console hiển thị câu nháp bị chặn kèm lý do trong panel "Minh bạch", đó chính là "cảnh báo khi agent sắp cam kết sai" của C.6 M2.
- **Chế độ copilot, gợi ý:** gợi ý hiện kèm huy hiệu cảnh báo và lý do; nhân viên thấy trước khi dùng.
- **Chế độ copilot, câu nhân viên gõ:** `human_send` chạy `guard_hard` rồi `guard_soft` trên chính câu nhân viên; có vi phạm thì `interrupt` lần nữa để hiện cảnh báo, nhân viên có thể sửa hoặc gửi kèm lý do ghi đè, cả hai đều ghi vào `signals`. Đây là mục điểm thưởng "phát hiện realtime khi nhân viên cam kết sai chính sách", và nó gần như miễn phí vì guard đã có.

Không có agent nào tên WarningAgent, và khi bị hỏi thì câu trả lời là: cảnh báo là một `violation` của PolicyAgent được render ở nơi khác.

---

## 12. Fallback · hình 12

*Nhận vào: một tín hiệu lỗi từ bất kỳ node nào. Trả ra: một câu nói cụ thể với khách và một hành động cụ thể của hệ thống.*

| Sự cố | Phát hiện | Hệ thống nói gì | Hệ thống làm gì |
|---|---|---|---|
| tool timeout hoặc lỗi | adapter trả `{ok:false, retryable}` | "Dạ hệ thống bên em đang tra cứu hơi chậm, em xin phép nhắn lại chị trong ít phút ạ" | thử lại một lần, **không đoán số**, gọi `schedule.callback` nếu được, tăng `flags.tool_health`, hỏng liên tiếp thì lane HANDOFF |
| ASR trả rác | `asr_low_conf` dưới ngưỡng, hoặc ITN không đọc ra số | "Dạ em nghe chưa rõ, chị đọc lại giúp em số điện thoại ạ" | lane CLARIFY, hỏi một câu ngắn, không đoán nội dung |
| model trả sai định dạng | structured output parse thất bại | thử lại một lần với prompt sửa; thất bại nữa thì `safe_default` theo lane | ghi `flags.format_error` |
| không tìm thấy bộ nhớ | `brief=None` với tier VERIFIED | chạy như khách mới, **không giả vờ nhớ** | lane NEW |
| bộ nhớ mâu thuẫn | fact `disputed` trong brief | "Dạ để em xác nhận lại, hôm trước bên em báo chị 4.890.000 đúng không ạ?" | câu xác nhận, không tự chọn bên |
| ngoài phạm vi | `oos_early` hoặc `oos_late` | thừa nhận trước: "Dạ phần này em chưa có thông tin chính xác", rồi đề nghị chuyển người | ghi signal, mục 13 nếu khách đồng ý |
| hết trần sinh lại | `regen_count = 2` | `safe_default` theo lane, ví dụ "Dạ để em kiểm tra kỹ rồi phản hồi chị ngay ạ" | ghi log, tăng đếm; hai lần trong một cuộc thì lane HANDOFF |
| MCP server chết | health check của adapter | như tool lỗi | circuit breaker: bỏ qua tool đó trong 60 giây |

`ADMIT FIRST` được ghi ngay trên hình vì đây là chỗ dễ mất điểm nhất: bịa rồi mới chuyển thì trượt TSR và ăn thêm Hallucination Rate.

`order.status` và `order.update` là M2 nhưng persona "khách đã mua gọi lại đổi size" là M1. Ở M1 Advisor thừa nhận không tra được trạng thái đơn rồi bàn giao, và báo cáo ghi rõ đó là lựa chọn có cân nhắc. Bật `ff.order_service` là ca đó đi lane ORDER_SERVICE đầy đủ.

---

## 13. Handoff · hình 13

*Nhận vào: `Command(goto="handoff")` từ `route`. Trả ra: một Handoff Brief cho người, và cuộc gọi tiếp tục ở chế độ copilot trên cùng thread.*

Handoff không phải kết thúc. Nó là **chuyển mode**. Đây là cách gọn nhất để Case 3 và mục copilot M2 dùng chung một cơ chế.

### 13.1 Bốn nguyên nhân, một cơ chế

| Nguyên nhân | Ai kích | M |
|---|---|---|
| ngoài phạm vi và khách muốn gặp người | Orchestrator sau khi Advisor đã thừa nhận | M1 |
| vượt thẩm quyền chính sách | Policy chặn hai lần cùng loại | M2 |
| sự cố kỹ thuật không tự phục hồi | `tool_health`, hết trần sinh lại hai lần | M1 |
| bàn giao giữa ca | lịch: cuối ca, hoặc nhân viên phụ trách vắng | M1 |

### 13.2 Cơ chế trong graph

1. Node `handoff` gọi `render_handoff(state, ledger)`, hàm thuần chung dữ liệu với `render_brief` nhưng viết cho người đọc trong mười giây.
2. Ghi một dòng `handoffs{call_id, reason, brief, status=pending, created_at}`.
3. Đặt `mode=copilot`, `flags.handoff_requested=true`.
4. `respond` phát câu nối với khách: "Dạ em kết nối chị với đồng nghiệp phụ trách ngay ạ, chị chờ em một chút" rồi gọi `interrupt({"kind":"handoff", "handoff_id":...})`. Graph dừng, checkpoint lưu. Chi tiết hiện thực cần nhớ: khi resume, LangGraph chạy lại node chứa `interrupt` từ đầu, nên việc phát câu nối phải idempotent (kiểm tra `reply` đã có chưa) hoặc tách thành node `bridge` đứng trước node chỉ có `interrupt`.
5. Agent Console hiện thẻ bàn giao. Nhân viên bấm "Nhận máy". Api gọi `Command(resume={"accepted_by": ...})`, `handoffs.status=accepted`.
6. Từ đó mỗi lượt khách đi qua graph bình thường, nhưng `respond` ở mode copilot chỉ đưa gợi ý (mục 14). Nhân viên là người nói.
7. Cúp máy: đường nguội chạy trên toàn bộ transcript, lượt của người tag `speaker=human_agent`. Cam kết do người hứa cũng được trích (M2) và cũng chịu guard trước khi gửi (mục 11.3).

### 13.3 Handoff Brief chứa gì

Khách là ai (tên hiển thị, bốn số cuối, tier, kênh đã dùng, số lần liên hệ); sản phẩm đã tư vấn kèm `quote_id`, giá, khuyến mãi, hạn; rào cản còn tồn đọng; cam kết đã hứa (M2); fact đang tranh chấp; ba lượt thoại cuối (khôi phục PII của chính khách); **lý do chuyển** và câu khách hỏi mà hệ thống không trả lời được; trạng thái đơn nếu có; việc cần làm tiếp; link trace.

Khác Call Brief ở chỗ: có lý do chuyển và ba lượt cuối, và viết thành đoạn ngắn thay vì dòng đánh số cho model.

### 13.4 Bàn giao giữa ca

Trang "Bàn giao ca" là một truy vấn: mọi `callbacks` đến hạn trong ca tới, mỗi dòng kèm Handoff Brief render tại chỗ, cộng các `handoffs` chưa đóng. Ca sáng hẹn "chiều gọi lại" thì ca chiều thấy đúng khách, đúng báo giá, đúng rào cản, không phải nghe lại ghi âm. Nhân viên nghỉ việc thì không mất gì vì brief là hàm của sổ cái, không phải của người.

**Phân biệt cần giữ:** Handoff Brief là bản tĩnh trao tay một lần; copilot là gợi ý chạy suốt cuộc gọi. Cái đầu bắt buộc M1, cái sau M2, nhưng chúng nối vào nhau ở bước 6.

---

## 14. Copilot · hình 14

*Nhận vào: một lượt khách trong thread có `mode=copilot`. Trả ra: một gợi ý có cảnh báo, rồi câu nhân viên thật gửi đi, cộng một tín hiệu 👍/👎.*

M2, `ff.copilot`. Dùng lại nguyên `AdvisorAgent`: mọi node trước `respond` không quan tâm ai đọc câu trả lời.

Vào chế độ copilot bằng hai đường: từ handoff (mục 13), hoặc nhân viên bật cho một phiên ngay từ đầu trên Agent Console (demo M2).

Vòng một lượt:

1. Khách gửi. Graph chạy `perceive → route → budget → advisor → guard_hard → guard_soft` như thường.
2. `respond` thấy `mode=copilot`: đặt `suggestion={text, guard, used_brief_lines}` và gọi `interrupt(suggestion)`. Graph dừng.
3. Agent Console hiện gợi ý, huy hiệu cảnh báo nếu Policy có `violations`, và brief bên cạnh. Nhân viên chọn: dùng nguyên, sửa, hoặc tự viết.
4. Api gọi `Command(resume={"text", "action": used|edited|own})`. Node `human_send` chạy `guard_hard` và `guard_soft` trên `text`. Có vi phạm thì `interrupt` lần hai để hiện cảnh báo; nhân viên sửa hoặc ghi đè kèm lý do. Cùng lưu ý resume chạy lại node từ đầu như mục 13.2: `human_send` không có side effect nào trước `interrupt` ngoài việc tính verdict, nên chạy lại là vô hại.
5. `human_send` ghi message với `speaker=human_agent`, phát ra cho khách, và ghi `signals{type: thumb, value: used→👍, edited→👎 kèm diff, own→👎}`.

**Tool nhạy trong copilot.** `order.create` ở mode copilot đi qua mẫu human-in-the-loop chuẩn của LangGraph: `interrupt` trước khi `ToolNode` thực thi, nhân viên duyệt tham số rồi mới tạo đơn. Ở mode speak thì không, vì đề chấm TSR bằng việc agent tự gọi `order.create`.

**Vì sao không làm hỏng bộ đánh giá.** Eval luôn chạy mode speak. Copilot chỉ là giá trị khác của một tham số ở node cuối, nên KPI số 1 vẫn tính trên câu agent hỏi, và simulator vẫn chạy tự động được.

**Vì sao có lợi cho tiêu chí 5.** Nút 👍/👎 là một trong bốn nguồn feedback đề liệt kê; không có copilot thì nguồn này không tồn tại. Có copilot thì nó tự sinh ra ở bước 5 mà không tốn thêm gì.

---

## 15. L4 MCP server và phân quyền · hình 15

*Nhận vào: yêu cầu gọi tool từ Advisor, từ harness prefetch, hoặc từ MemoryAgent. Trả ra: dữ liệu nghiệp vụ, với quyền được cấp ở đúng một chỗ.*

### 15.1 Server và tool

Mỗi server là một tiến trình FastMCP nhỏ, một file. Ở M1 chạy stdio, M2 chạy streamable-http trong compose; cùng code.

| Server | Tool | Vào | Ra | M |
|---|---|---|---|---|
| `mcp-memory` | `memory.get_profile` | `customer_id` | slot lõi, `need_attrs`, ghi chú mở đang `active` | M1 |
| | `memory.get_episodes` | `customer_id`, `n` | n episode gần nhất | M1 |
| | `memory.get_open_items` | `customer_id` | rào cản, fact `disputed`, callback đến hạn | M1 |
| | `identity.find` | `key_type`, `key_hash` | `customer_id`, `tier` | M1 |
| | `identity.link_provisional` | `customer_id`, khóa | ok | M1, vai `harness` |
| | `memory.commit_facts` | danh sách quyết định add/update/invalidate | `fact_ids` | M1, vai `memory_writer` |
| | `memory.commit_episode` | episode | `episode_id` | M1, vai `memory_writer` |
| | `memory.confirm_identity` | `customer_id`, khóa | ok | M1, vai `memory_writer` |
| | `memory.search_notes` | `customer_id`, câu hỏi | ghi chú liên quan | M2 |
| | `memory.delete_customer` | `customer_id` | số dòng xóa | M2, vai `admin` |
| `mcp-catalog` | `catalog.search` | câu hỏi, bộ lọc (`category`, `price_max`, `attrs`) | SKU, tên, giá niêm yết, thuộc tính, khuyến mãi đang hiệu lực | M1 |
| | `inventory.check` | `sku`, `variant` | còn hàng, số lượng | M1 |
| | `pricing.get_quote` | `sku`, `qty`, `customer_id`, `promo_code?`, hoặc `quote_id` để kiểm tra | `quote_id`, giá, khuyến mãi, `valid_until`; lỗi `EXPIRED_QUOTE` kèm báo giá mới | M1 (đề xếp M2, kéo lên vì `quote_id` là trục chống bịa giá) |
| `mcp-crm` | `crm.get_customer` | `customer_id` | tên hiển thị, phân khúc, số đơn | M1 |
| | `order.create` | `quote_id`, `variant`, `address_token`, `cod` | `order_id`, trạng thái; lỗi nếu quote hết hạn | M1 |
| | `schedule.callback` | `customer_id`, thời điểm, lý do | `callback_id` | M1 (đề xếp M2, kéo lên vì Phụ lục A.3 lấy nó làm assertion và thời điểm hẹn là slot bắt buộc M1) |
| `mcp-order` | `order.status` | `order_id` hoặc `customer_id` | trạng thái, vận đơn | M2 |
| | `order.update` | `order_id`, thay đổi | ok hoặc lỗi theo quy tắc (chỉ trước khi giao) | M2 |
| `mcp-knowledge` | `kb.search` | câu hỏi, `k`, bộ lọc | chunk kèm `chunk_id`, nguồn, điểm | M2 |
| | `kb.upsert` | chunk | ok | M2, vai `admin`, chỉ job apply gọi |

Hợp đồng lỗi chung: mọi tool trả `{ok, data | error{code, retryable, message}}`. Timeout 2 giây cho catalog và crm, 3 giây cho kb. Adapter thử lại một lần khi `retryable`.

### 15.2 Ba vai, một adapter

| Vai | Ai cầm | Được gọi |
|---|---|---|
| `advisor` | AdvisorAgent | mọi tool nghiệp vụ, `memory.get_*`, `memory.search_notes` |
| `harness` | `retrieve`, `refresh`, `resolve` | `memory.get_*`, `identity.*`, `pricing.get_quote(quote_id)`, `inventory.check`, `order.status` |
| `memory_writer` | graph nguội của MemoryAgent | `memory.commit_*`, `memory.confirm_identity` |
| `admin` | job apply, trang quản trị | `kb.upsert`, `memory.delete_customer` |

Adapter là `MultiServerMCPClient` khởi tạo với header vai; server có middleware kiểm tra vai trước khi chạy tool. Tool ghi không nằm trong danh sách bind cho Advisor nên model không nhìn thấy chúng, và nếu có cách nào đó gọi được thì server từ chối. Ba đường vào cùng qua adapter, không có đường vòng. Đây chính là "phân quyền theo tool" mà M2 đòi, và nó có từ M1 vì làm sau khó hơn làm trước.

### 15.3 `quote_id` là trục của chống bịa giá

Đây là cách e-commerce thật vận hành: báo giá có hiệu lực, đơn tham chiếu báo giá. Hệ quả cho bài:

- Advisor không cần nhớ giá; muốn nói là gọi, muốn chốt là truyền `quote_id`.
- `guard_hard` chỉ còn một câu hỏi: con số trong câu có nằm trong `tool_results` lượt này không.
- Assertion TSR của Phụ lục B rút thành `order.create` được gọi với đúng `quote_id`, hoặc đúng `sku` và `price` nếu muốn giữ đúng mẫu đề.
- Ca khuyến mãi hết hạn thành tất định: `order.create(Q-1071)` sau ngày 16/03 trả `EXPIRED_QUOTE`, Advisor buộc phải nói khuyến mãi hết và báo giá mới, không có cửa chiều khách.
- Chính sách giữ giá của doanh nghiệp (giữ tới hết hạn khuyến mãi, hay tới bảy ngày) nằm trong `valid_until` của tool, đổi một hằng số là đổi chính sách, không đụng prompt.

### 15.4 Vì sao MCP là câu trả lời chính thức cho C.3, và vì sao không dùng A2A

MCP vì lý do đánh giá: đặt bộ nhớ và nghiệp vụ sau một ranh giới server làm chúng thành thành phần gỡ ra được, nên baseline là một cấu hình chứ không phải nhánh code, và phân quyền là một header chứ không phải một lời hứa trong prompt. Điều đó nối 15% của mục MCP thẳng vào 15% của mục đánh giá. Nói cho chính xác trên slide: baseline là công tắc ở `retrieve`, không phải việc gỡ server, vì gỡ hẳn `mcp-memory` thì `persist` và `refresh` chết theo, tức đổi nhiều hơn một biến.

Không dùng giao thức A2A, vì bốn lý do, và nên nói cả bốn khi phản biện:

1. Đề cho chọn một trong hai. MCP đã là câu trả lời.
2. A2A giả định các agent là hộp đen của các bên khác nhau trao đổi task qua HTTP, nghĩa là **không** chia sẻ state. Hệ này cố tình cho các agent dùng chung một `HotState` và một checkpointer, và đó chính là thứ rubric yêu cầu chứng minh ("agent có thật sự chia sẻ trạng thái không"). Dùng A2A là bỏ đi điểm mạnh để lấy một cái tên.
3. A2A thêm agent card, task lifecycle, xác thực giữa agent, mà không dòng nào trong rubric chấm.
4. Chỗ duy nhất A2A hợp là `MemoryAgent` đường nguội, vì nó đã là tiến trình riêng nhận một task; nhưng nó đã là một job trong bảng `jobs`, và một hàng đợi Postgres làm đúng việc đó với ít hơn một giao thức.

Gọi đúng tên: **multi-agent theo Hướng 2, hiện thực bằng LangGraph subgraph, chia sẻ state, chuyển giao bằng `Command`.** Không gọi là A2A.

---

## 16. Truy vết · hình 16

*Nhận vào: một câu agent đã nói, hoặc một fact trong sổ cái. Trả ra: đường đi ngược về lượt thoại sinh ra nó, và màn hình để QA xem.*

Hai lớp, vì hai câu hỏi khác nhau.

### 16.1 Lớp dữ liệu: nguồn gốc của ký ức

Mọi bản ghi đều mang khóa ngược:

| Từ | Về | Bằng cột |
|---|---|---|
| câu agent nói (`messages.meta`) | dòng brief đã dùng | `used_brief_lines` do Advisor trả |
| dòng brief (`briefs.lines`) | fact | `fact_ids` |
| fact (`facts.source`) | lượt thoại | `call_id`, `turn_id`, `span`, `extractor_version` |
| episode | đoạn lượt | `source_turn_span` |
| lượt thoại (`raw_transcripts`) | audio và giá trị PII | `audio_ref`, token trong `pii_vault` |
| câu agent nói | tool đã gọi | `tool_call_ids`, tham số và kết quả trong `messages.meta` |
| câu agent nói | guard | `guard.hard`, `guard.soft`, `regen_count`, `block_reasons` |
| đề xuất cải tiến (`proposals`) | tín hiệu | `source_signal_ids` → `signals.call_id, turn_id` |

Nghĩa là từ một câu "hôm trước bên em báo chị 4.890.000" chỉ ngược được: dòng B3 của brief → fact `quote` → cuộc 1 lượt 14 → transcript gốc → file ghi âm, cộng tool call `pricing.get_quote` lượt này và verdict của guard. Bốn nơi cần lớp này: yêu cầu truy vết nguồn gốc M2; phân tích mười ca sai trong báo cáo (cần nguyên văn); thu hồi cả cụm khi phát hiện fact độc; tính lại WER khi đổi chuẩn hóa.

### 16.2 Lớp chạy: Langfuse

`CallbackHandler` của Langfuse gắn vào mọi `invoke` của graph nóng, graph nguội và eval runner. Metadata trace: `call_id`, băm `customer_id`, `mode`, `switches`, `scenario_id` và `run_name` khi là eval. `session_id = customer_id` để mọi cuộc của một khách gom về một chỗ. Trace chỉ chứa text đã tokenize nên PII không rời hệ thống, và xóa khách không cần đụng Langfuse.

Langfuse trả lời câu "prompt thật sự gửi đi là gì, model trả gì, mất bao lâu, tốn bao nhiêu token". Bảng của mình trả lời câu "câu này dựa vào fact nào, fact đó từ đâu". Điểm chấm từ eval được đẩy lên Langfuse dưới dạng score gắn vào trace, và mỗi lần chạy golden set là một dataset run (mục 17.2).

Độ trễ: handler gửi theo lô bất đồng bộ; số đo trễ báo cáo lấy từ timer trong `reply`, không lấy từ Langfuse, để không phụ thuộc mạng.

### 16.3 Trang QA Review

Chọn cuộc gọi → cột trái là timeline lượt thoại; bấm một lượt agent → cột phải hiện: dòng brief đã dùng (bấm vào nhảy tới lượt gốc ở cuộc trước), tool call với tham số và kết quả, verdict guard và câu nháp bị chặn nếu có, link trace Langfuse; phía dưới là điểm rubric của QaAgent (M2) và form chấm tay cùng rubric để tính kappa. Cùng một trang phục vụ ba việc: soi lỗi, chấm mẫu, và đối chiếu người với máy.

Timeline bộ nhớ của khách (bắt buộc M1) là một truy vấn trên `facts` và `episodes` theo thời gian, hiển thị ngay trong Agent Console: hệ thống biết gì, từ khi nào, từ kênh nào.

---

## 17. L5 đánh giá · hình 17a, 17b, 17c

*Nhận vào: golden set đóng băng. Trả ra: một bảng số so hệ thống với baseline, tái lập bằng một lệnh, cộng danh sách ca sai đẩy sang mục 18.*

### 17.1 File kịch bản

Mọi thứ dùng để chấm được khai báo trước, không ai phải ngồi nghe. Mở rộng mẫu Phụ lục B của đề bằng bốn thứ còn thiếu:

```
scenario_id, persona, tags (ca khó nào), customer {phone, channels}
calls[]:
  channel, days_later, now
  customer_script {opening, goal, answers{slot: câu trả lời}, confirm_reply,
                   buy_if_offered, wants_human_if_oos, max_turns}
  facts_established {...}                      // cuộc 1
  must_carry_over [...]                        // CCR
  must_not_ask [...]                           // RQR
  expected_tool_calls [{name, args_subset}]    // Tool-Call Accuracy, M2
  success_if {graded_by: assertion | judge, assertion{tool, args_match} | rubric_id}
  ground_truth_facts {price, promo_active, in_stock, delivery_days}   // HR
  catalog_snapshot_id                          // trạng thái catalog và khuyến mãi tại `now`
```

`customer_script` là thứ bản trước thiếu. Ở M1 chưa có simulator, phía khách phải chạy bằng gì? Bằng một **responder luật** `ScriptedCustomer`: nếu câu agent vừa hỏi ánh xạ được về một slot (dùng cùng bộ phân loại câu hỏi ở 17.4) thì trả lời theo `answers`, câu xác nhận thì trả `confirm_reply`, agent đề nghị chốt và `buy_if_offered` thì đồng ý, còn lại đọc dòng kịch bản tiếp theo, dừng ở `max_turns` hoặc khi assertion đã thỏa. Tất định hoàn toàn. M2 thay bằng `SimulatorAgent` (17.6) mà không đổi file kịch bản.

`catalog_snapshot_id` cộng `now` là điều kiện để ca khuyến mãi hết hạn tái lập.

Ba lớp tập: **golden** (M1 ≥ 20 kịch bản đa phiên + ≥ 5 ca khó; M2 ≥ 40), đóng băng, chỉ để đo; **growth**, nhận ca mới từ mục 18, để canh không tái phạm; **asr_eval**, ≥ 20 file. Tách khách chứ không tách cuộc gọi giữa các tập, vì khách đa phiên nằm ở nhiều cuộc.

### 17.2 Runner và một lệnh

`python -m eval run --set golden --memory both --round r1` làm theo thứ tự cho từng kịch bản: tạo sandbox (schema Postgres riêng hoặc một transaction rollback), nạp `catalog_snapshot`, đặt `now`, chạy cuộc 1 với `ScriptedCustomer` đối thoại với graph nóng ở mode speak, gọi `end` và **chạy graph nguội đồng bộ** (không qua worker, vì cuộc 2 cần fact đã ghi), tiến đồng hồ theo `days_later`, chạy cuộc 2, cuộc 3. Thu transcript, tool log, state, latency. Chạy lại toàn bộ với `switches.memory=off`. Đưa cả hai vào cùng khối chấm. In bảng A.6 của đề, thêm ba dòng: CCR và RQR phụ trên tập TSR đạt, số lượt trung bình mỗi kịch bản, và WER/CER/Entity từ `score_asr()`. Ghi `reports/<run_id>/{metrics.json, table.md, errors.jsonl, manifest.json, llm_cache.sqlite}`. Nếu có Langfuse thì mỗi run là một dataset run với `run_metadata` là manifest.

Tính tái lập đến từ năm thứ: `temperature=0` mọi lời gọi; đồng hồ ảo; `faq_version`, `exemplar_version`, `playbook_version` ghim trong manifest; LLM cache theo lời gọi; và `catalog_snapshot`. Phụ lục D giải thích cache và manifest.

`python -m eval compare r0 r1` in bảng chênh lệch và **từ chối so sánh** nếu hai manifest khác nhau ở bất kỳ trường nào ngoài các trường được phép khác (`switches.memory`, `faq_version`, `exemplar_version`, `playbook_version`). Đây là luật "cùng bộ test, cùng model, cùng tham số" của đề được thi hành bằng code.

### 17.3 Baseline

Cùng graph, cùng prompt, cùng tool, cùng cache. Khác đúng một bit: `switches.memory=off` làm `retrieve` trả `brief=None`. Đường nguội vẫn chạy để ghi sổ cái (để không thay đổi thêm biến nào), chỉ là cuộc sau không đọc. Exemplar bật ở cả hai bên (8.2).

### 17.4 Bốn bộ chấm

| Bộ chấm | Cách | Chỉ số |
|---|---|---|
| `question_classifier` | model nhỏ `temperature=0`, structured output `{is_question, type: open \| confirm, slot}`, đi qua cache của scorer nên chạy lại ra đúng nhãn cũ; **kèm bảng độ chính xác trên 50 câu gán tay** báo trong báo cáo | RQR = câu mở về slot trong `must_not_ask` / tổng câu hỏi |
| `fact_usage_checker` | tất định: fact trong `must_carry_over` được tính khi xuất hiện trong tham số tool, hoặc trong lượt khác lượt chào, hoặc trong lượt chào dưới dạng câu xác nhận; chuẩn hóa số trước khi so | CCR |
| `assertion_runner` | chạy `success_if.assertion` trên tool log; kịch bản `graded_by: judge` đi sang 17.5 | TSR |
| `claim_extractor` | model nhỏ `temperature=0` có cache, tách claim `{type: price \| promo \| stock \| delivery \| policy, value}`; đối chiếu bằng code với `ground_truth_facts`; báo HR chung và HR riêng cho giá và khuyến mãi | HR |
| `score_asr` | `jiwer` với chuẩn hóa đã công bố; entity exact match sau ITN; tách theo miền | WER, CER, Entity Accuracy |

Lý do bộ phân loại dùng model: ánh xạ câu hỏi tiếng Việt tự do về slot bằng luật là việc khó hơn nó trông và sẽ gãy ở tuần ba. Tái lập đến từ cache và manifest, không nhất thiết từ luật; điều phải làm là **công bố độ chính xác của thước đo** trên mẫu gán tay. Tự vạch giới hạn thước đo của mình là thứ ăn điểm ở tiêu chí 8.

Chống lách mà không hỏng phép so: không lọc theo TSR ở số chính (baseline trượt nhiều hơn nên tập con khác thành phần, mức giảm 40% thành không diễn giải được); báo số chính trên toàn bộ, thêm cột phụ trên tập TSR đạt. Chống đọc vẹt bằng proxy tất định của `fact_usage_checker`; nói rõ đó là xấp xỉ quy tắc "phục vụ đúng mục đích" của đề.

### 17.5 Chỉ số M2 và judge

| Chỉ số | Cách đo |
|---|---|
| Calls-to-Close | từ các lượt chạy simulator: số cuộc trung bình tới `order.create` thành công trên các kịch bản có `buy_if_offered` |
| Tool-Call Accuracy | tool call đúng tên và tham số con khớp `expected_tool_calls` / tổng tool call kỳ vọng |
| Recall@k | bộ `kb_eval`: câu hỏi → `chunk_id` vàng; `kb.search(k=3, 5)` |
| latency p50/p95 | `ttft`, `ttft_content`, tổng lượt, thời gian nạp brief, từ timer trong state |
| chi phí mỗi cuộc | token vào ra từng lời gọi × đơn giá, tách đường nóng và đường nguội |

**Judge là `QaAgent`.** Rubric là danh sách mục nhị phân đạt hoặc không, mỗi loại kịch bản một rubric (ví dụ ca tiếp nối: mở đầu có xác nhận tiếp nối; không hỏi mở về slot đã biết; nêu đúng sản phẩm và giá từ tool; xử lý rào cản; giọng điệu đúng). Kịch bản nào chấm bằng assertion, kịch bản nào bằng judge được khai báo trong `graded_by`. Đối chiếu với người trên ≥ 20 mẫu qua trang QA Review, báo **kappa** chứ không phải phần trăm khớp thô, vì nếu 80% mẫu là đạt thì một giám khảo luôn trả lời đạt vẫn khớp 80%.

### 17.6 `SimulatorAgent` (M2, `ff.simulator`)

Đóng vai khách theo persona của kịch bản, chỉ được nói những fact trong `customer_script`, `temperature=0`. State quan trọng nhất là **mức kiên nhẫn**: bắt đầu 3, giảm 1 mỗi lần bị hỏi mở về slot đã trả lời (phát hiện bằng chính `question_classifier` chạy trực tiếp), về 0 thì nói "em hỏi rồi mà" và cúp máy. Không có mức kiên nhẫn thì simulator sẽ vui vẻ trả lời lại lần thứ năm và hệ thống trông tốt hơn thực tế. Persona M2 "gọi lần 3 đã hết kiên nhẫn" là kiên nhẫn khởi đầu 1.

### 17.7 Xuất ca sai

`errors.jsonl` liệt kê mọi kịch bản trượt bất kỳ chỉ số nào, kèm `call_id` để mở trên QA Review. Đây vừa là nguyên liệu cho phần phân tích ≥ 10 ca sai của báo cáo, vừa là một nguồn tín hiệu của mục 18.

---

## 18. L6 cải tiến · hình 18a, 18b, 18c, 18d

*Nhận vào: tín hiệu từ đường nóng, đường nguội và eval. Trả ra: một phiên bản mới của FAQ, exemplar bank hoặc playbook, đã có người duyệt, đo được trên golden set, và thu hồi được.*

Ràng buộc của đề: không huấn luyện lại. Mọi cải tiến là dữ liệu, bộ nhớ, prompt, điều phối. Ba cơ chế chung một hạ tầng: bảng `signals`, bảng `proposals`, một trang duyệt, một job apply có version, một job rollback.

### 18.1 Nguồn tín hiệu

Đề cho bốn nguồn, M1 cần hai. Chọn cả bốn vì cả bốn đã có sẵn: **kết quả cuộc gọi** (slot `outcome`, bắt buộc M1); **điểm chấm tự động** (`errors.jsonl` của 17.7 và điểm QaAgent M2); **👍/👎 của nhân viên** (mục 14, M2); **khách phải nhắc lại** (ghi khi `question_classifier` chạy trực tiếp thấy câu mở về slot đã có, hoặc khách nói "em nói rồi mà"; khác RQR ở chỗ đo phía khách và chạy thật trong hội thoại). Cộng hai tín hiệu ngoài phạm vi `oos_early`, `oos_late` từ mục 9 và 10.

Nguồn phát hiện và tập đo phải tách: gap tìm từ kho hội thoại dataset và các lượt chạy simulator, **không bao giờ từ golden set**. Nếu gap được phát hiện từ golden rồi vá rồi đo lại trên golden thì đó là học thuộc đề.

### 18.2 Knowledge Gap Loop (M1) · hình 18a

Job `collect` (chạy bằng lệnh hoặc lịch tuần) gom `signals` loại ngoài phạm vi và khách nhắc lại. Job `cluster` nhúng câu hỏi bằng embedding API và gom cụm bằng ngưỡng khoảng cách; với dataset M1 là bốn mươi tới sáu mươi tín hiệu nên đây là nửa buổi công, đáng làm vì nó đổi một danh sách phẳng thành một danh sách có ưu tiên, nhưng đừng gọi nó là phần khó. Mỗi cụm thành một `proposal{kind: faq, cluster_label, count, examples, draft_answer}` với câu trả lời nháp do model viết để người duyệt sửa.

Trang Cải tiến hiện đề xuất, hai nút duyệt và từ chối, ô sửa câu trả lời. Duyệt xong, job `apply` ghi `faq_block` phiên bản mới (file text, băm vào manifest) và thêm ca test vào **growth set, không phải golden**. Đây là bẫy nhiễm dữ liệu đa số nhóm sẽ dính, vì đề vừa yêu cầu tự động thêm ca test vừa yêu cầu chạy lại trên cùng bộ test giữ nguyên.

Đầu ra phải có người tiêu thụ: `budget` nhét khối FAQ vào prompt của Advisor ở M1. Ở M2 khối này được `kb.upsert` vào KB và `budget` chuyển sang top-k. Không có người tiêu thụ thì vòng 1 ra đúng số vòng 0.

### 18.3 Exemplar Bank (M2, `ff.exemplars`) · hình 18b

Cơ chế duy nhất trong L6 chảy ngược vào đường nóng qua `retrieve`. Tuyển vào bank chỉ những cuộc **vừa chốt được vừa qua `policy_clean`**: mọi lượt agent qua `guard_soft` chạy lại ở đường nguội, HR về giá bằng 0. Tuyển theo tỷ lệ chốt thuần thì cuộc chốt nhờ hứa liều sẽ lọt vào bank, thành ví dụ mẫu, và dạy hệ thống rằng hứa liều là chiến lược tốt. Chặn ở đầu vào rẻ hơn sửa sau. Vẫn qua trang duyệt.

Chọn ví dụ theo cặp `objection_type` và `persona`, không theo độ gần ngữ nghĩa, vì cái cần học là cách xử lý chứ không phải nội dung sản phẩm; trong nhóm chọn cái có kết quả tốt nhất; `diversify` để ba ví dụ không trùng nhau. Exemplar nằm cuối ưu tiên `budget`, chật thì bị cắt đầu tiên.

### 18.4 Reflection và playbook (M2, `ff.reflection`, cần `ff.qa_agent`) · hình 18c

Chọn thay cho A/B test, vì A/B cần lưu lượng: hai mươi tới bốn mươi kịch bản chia hai biến thể thì mỗi bên mươi mẫu, chênh lệch nào cũng nằm trong nhiễu. Reflection không so sánh mà tích lũy nên không cần cỡ mẫu, và nó gần như miễn phí khi QaAgent đã chấm cuộc gọi: viết bài học là prompt thứ hai trong cùng graph.

Cửa lọc `{call worth learning from?}` đứng trước: chỉ cuộc mất đơn, có phản đối được xử lý, có câu ngoài phạm vi, hoặc có fact tranh chấp. Viết sau mỗi cuộc thì 250 cuộc là 250 đề xuất, hàng đợi ngập và người duyệt bấm cho xong.

Bài học **có cấu trúc** `{objection_type, persona, situation, what_worked, what_failed, suggested_line, source_call_id}`. Cửa tự động `{schema + policy check}` chạy trước cửa người: đúng khuôn, không vi phạm chính sách, không mâu thuẫn mục đã duyệt. Playbook là danh sách mục có mã và trạng thái (đề xuất, đã duyệt, đã thu hồi), mỗi vòng thêm sửa thu hồi vài mục, **không để model viết lại cả file**, vì viết lại toàn khối làm chỉ dẫn ngắn dần và chi tiết mòn dần qua mỗi vòng.

### 18.5 Vòng, quay lui, và cải tiến gây hại · hình 18d

| Vòng | Cấu hình | Mức |
|---|---|---|
| R0 | `faq_v0`, exemplar tắt, playbook tắt; chạy baseline và hệ thống | M1 |
| R1 | `faq_v1` từ Gap Loop; còn lại như R0 | M1 |
| R2 | R1 cộng exemplar bank và playbook bật | M2 |
| R3 | chu kỳ gap thứ hai, `faq_v2` | M2 |

Tất cả trên golden đóng băng, cùng manifest trừ trường version. Growth set báo riêng.

**Quay lui** là đổi con trỏ version: `faq_active=v0`, mục playbook chuyển `revoked`. Job `rollback` tự chạy khi `eval compare` cho thấy RQR tăng, TSR giảm hoặc HR về giá vượt 5% so với vòng trước.

**Phân tích cải tiến gây hại (M2)** là ablation theo mục: tắt từng mục playbook hoặc từng cụm exemplar, chạy lại golden, ghi delta. Mục có delta âm thì thu hồi và đưa vào báo cáo với transcript minh họa. Đây đồng thời là mục điểm thưởng "ablation chỉ ra cơ chế nào thực sự tạo khác biệt".

**Chống học nhầm "hứa đại cho khách chốt"** ba lớp: `policy_clean` ở cửa vào bank; `schema + policy check` ở cửa vào playbook; và một unit test gieo sẵn một cuộc chốt đơn nhờ hứa sai chính sách, khẳng định nó bị từ chối ở cả hai cửa.

**Ai duyệt cái gì.** Mọi thay đổi chạm vào lời hứa với khách hoặc chính sách (FAQ, playbook, exemplar) cần người duyệt; bổ sung ca test vào growth set thì tự động. Người duyệt là QA hoặc tư vấn viên: tư vấn viên biết câu nào chốt được, QA biết câu nào vi phạm. Ở quy mô này cửa duyệt là một trang hai nút, không phải hệ thống hàng đợi có audit log; nói đúng quy mô để không bị hỏi những câu không có gì để trả lời.

---

## 19. L7 giao diện · hình 19

Streamlit multipage, sáu trang, gọi `api`. Hai phiên đồng thời là hai tab Chat với `thread_id` khác nhau; Agent Console liệt kê các thread đang mở.

| Trang | Có gì | M |
|---|---|---|
| Chat | khung hội thoại của khách, câu đệm, streaming | M1 |
| Agent Console | Call Brief hiện khi khách gọi lại; timeline bộ nhớ; panel Minh bạch (lane, tool call, verdict guard, câu nháp bị chặn); thẻ bàn giao và nút Nhận máy; gợi ý copilot kèm cảnh báo; 👍/👎 | M1, phần copilot và cảnh báo M2 |
| QA Review | mục 16.3 | M1, phần rubric máy M2 |
| Cải tiến | đề xuất, duyệt, từ chối, version đang hoạt động, nút quay lui | M1 |
| Dashboard | bảng chỉ số của run mới nhất, biểu đồ theo vòng, latency p50/p95, chi phí | M2 |
| Bàn giao ca | mục 13.4 | M1 |

Đề nói không cần đẹp. Cái cần là **thấy được bộ nhớ hoạt động**: brief xuất hiện đúng lúc, timeline có nguồn, câu nháp bị guard chặn hiện lên. Đó là ba thứ giám khảo nhớ sau demo.

---

## 20. Tương tác giữa các agent · hình 20

Harness là luồng điều khiển: node nào chạy trước node nào. Đồ thị agent là quyền sở hữu và trao đổi: ai chịu trách nhiệm gì và giao nhau cái gì. Cùng một hệ thống, hai lát cắt; đề đòi cả hai vì nó hỏi thẳng "các agent có thật sự chia sẻ trạng thái và chuyển giao nhiệm vụ không".

**Ba loại trao đổi.** Trạng thái dùng chung: một `HotState`, một checkpointer, không ai giữ bản sao riêng. Chuyển giao có điều kiện: Orchestrator → Advisor hoặc → handoff bằng `Command`; Advisor → Policy bằng chiếu state chỉ còn `draft` và `tool_results`; Policy → Advisor bằng `block_reasons` chứ không chỉ đạt hay trượt, vì Advisor cần lý do mới soạn lại được. Bàn giao qua nhịp: harness giao transcript cho MemoryAgent lúc cúp máy; chiều ngược lại ở cuộc sau **không đi qua MemoryAgent** mà harness prefetch trực tiếp, nghĩa là MemoryAgent chỉ đứng ở chiều có phán đoán.

**Nguyên tắc phân vai.** Không agent nào vừa tạo ra thứ gì đó vừa tự phê duyệt nó. Advisor soạn thì Policy duyệt. Advisor nói thì Memory quyết ghi gì. QA chấm thì không nằm trong mạch tạo ra thứ bị chấm.

**Phép thử để được gọi là agent:** gộp nó vào agent bên cạnh thì hỏng cái gì. Gộp Orchestrator vào Advisor thì mọi lượt phải nạp toàn bộ ngữ cảnh bán hàng vào model lớn kể cả lượt chỉ cần định tuyến, mất tính tất định của router. Gộp Memory vào Advisor thì cái model vừa bị khách dẫn dắt cũng chính là cái quyết định ghi gì. Gộp QA vào bất kỳ ai thì thứ chấm điểm nằm chung với thứ bị chấm.

**Tình huống mang đi phản biện, bản M1:** `AdvisorAgent` cầm client bộ nhớ chỉ đọc, chỉ graph nguội của `MemoryAgent` có quyền ghi. Khách nói đùa "anh mua cho công ty năm trăm người": nếu ghi và nói là một agent thì câu đùa thành sự thật vĩnh viễn; tách ra thì phát ngôn đi qua cổng ghi ở nhịp khác, model khác, có luật ưu tiên và trạng thái tranh chấp. Không phải luật trong prompt mà là ràng buộc ở ba tầng (mục 3.4).

**Bản M2, mạnh hơn:** khách đòi áp khuyến mãi hết hạn. Advisor có trong ngữ cảnh cả brief cũ ghi 4.890.000, lời khách nài, và tool báo 5.200.000; với ngần ấy áp lực trong một cửa sổ, model dễ soạn câu chiều khách. Nếu Policy dùng chung ngữ cảnh thì nó thấy đúng những thứ đã khiến Advisor mềm lòng, và gật. Cho Policy nhìn **ít hơn**, chỉ câu nháp cộng kết quả tool, thì nó thấy một khẳng định 4.890.000 đứng cạnh dữ kiện 5.200.000, và chặn. Giá trị của việc tách nằm ở chỗ agent thứ hai nhận ít thông tin hơn, và điều đó không giả vờ được bằng cách đổi tên một prompt.

---

## 21. Kiểm kê · hình 21

| Loại | M1 | M2 |
|---|---|---|
| Agent sản phẩm | `OrchestratorAgent`, `AdvisorAgent`, `MemoryAgent` | + `PolicyAgent`, `QaAgent` |
| Agent chỉ trong eval | | `SimulatorAgent` |
| Node code graph nóng | `perceive`, `resolve`, `retrieve`, `refresh`, `budget`, `guard_hard`, `safe_default`, `respond`, `handoff` | + `compact`, `human_send` |
| Node graph nguội (thuộc MemoryAgent) | `load`, `extract`, `gate`, `commit`, `summarize` | + `enqueue_qa` |
| Node graph QaAgent | | `score`, `reflect`, `check`, `propose` |
| Job | `persist`, `collect`, `cluster`, `apply` | + `rollback`, `ablation` |
| MCP server | `mcp-memory`, `mcp-catalog`, `mcp-crm` | + `mcp-order`, `mcp-knowledge` |
| Bảng | `facts`, `episodes`, `identities`, `raw_transcripts`, `messages`, `briefs`, `quotes`, `orders`, `callbacks`, `handoffs`, `signals`, `proposals`, `faq_block`, `jobs` | + `pii_vault`, `kb_chunks`, `exemplars`, `playbook`, `human_scores` |

Slide M1 chỉ trình bày cột M1. Nói được cách phân loại này là câu trả lời cho câu hỏi "các agent có phối hợp thật không".

---

# Phụ lục A · Bản đồ M1 → M2 bằng feature flag

Mỗi flag tắt là M1 nguyên vẹn. Mỗi flag bật là thêm đúng những thứ ghi ở cột "thêm gì".

| Flag | Thêm gì | Khi tắt | Mục đề |
|---|---|---|---|
| `ff.audio_repair` | node repair trong `ingest`: từ điển, diarization, nhiễu | transcript thô sau ASR | C.1 voice M2 |
| `ff.pii_vault` | bảng `pii_vault`, token khôi phục được, tool `memory.delete_customer` | regex che một chiều | C.1 PII M2 |
| `ff.ttl_decay` | cột `ttl_policy`, khung nhìn `current_facts` lọc theo `now` | fact không hết hạn | C.1 bộ nhớ M2 |
| `ff.anti_poison` | thu hồi cả cụm theo `source` khi hai nguồn phủ nhận | chỉ `disputed` | C.1 bộ nhớ M2 |
| `ff.unknown_number` | lane CONFIRM_IDENTITY nâng tier trong cuộc | số lạ là khách mới | C.2 M2 |
| `ff.order_service` | `mcp-order`, lane ORDER_SERVICE, cuộc 3 demo | thừa nhận rồi bàn giao | C.2, C.3, C.6 M2 |
| `ff.kb_rag` | `mcp-knowledge`, `kb_chunks`, `budget` chuyển FAQ sang top-k, Recall@k | khối FAQ phẳng trong prompt | C.1, C.3, C.4 M2 |
| `ff.compact` | node `compact` | cắt theo `budget`, không nén | C.2 M2 |
| `ff.policy_agent` | node `guard_soft`, `policy_snippets`, cảnh báo | chỉ `guard_hard` | C.3 M2, C.6 M2 |
| `ff.qa_agent` | graph QaAgent, rubric, kappa, `human_scores` | chỉ assertion | C.3, C.4 M2 |
| `ff.simulator` | `SimulatorAgent`, Calls-to-Close | `ScriptedCustomer` | C.4 M2 |
| `ff.m2_metrics` | Tool-Call Accuracy, latency, chi phí trong bảng | 5 chỉ số M1 | C.4 M2 |
| `ff.exemplars` | bảng `exemplars`, `policy_clean`, `retrieve` nạp exemplar | không exemplar | C.5 M2 |
| `ff.reflection` | node `reflect`, `check`, `propose`, bảng `playbook` | không playbook | C.5 M2 |
| `ff.ablation` | job `ablation`, báo cáo cải tiến gây hại | so vòng bằng tay | C.5 M2 |
| `ff.copilot` | `interrupt` ở `respond`, node `human_send`, 👍/👎 | chỉ speak và handoff tĩnh | C.6 M2 |
| `ff.dashboard` | trang Dashboard | đọc `table.md` | C.6 M2 |
| `ff.concurrent` | compose đầy đủ, MCP streamable-http | một tiến trình, stdio | C.2 hiệu năng M2 |

Không có flag cho: voice real-time, barge-in, TTFA, streaming ASR, voiceprint, hai người chung một số, tách hồ sơ đã gộp. Với mỗi cái, báo cáo ghi chỗ sẽ gãy nếu làm (voice ăn ba tuần và là lỗi mất điểm số một; hai người chung số phá giả định một số một khách nằm ngay trong định dạng file test), để việc không làm là quyết định có cân nhắc chứ không phải chưa kịp.

---

# Phụ lục B · Rubric → bằng chứng

| # | Tiêu chí | % | Bằng chứng cụ thể trong sản phẩm | Nơi trong tài liệu |
|---|---|---|---|---|
| 1 | Dữ liệu & tiếng Việt | 12 | dataset có ≥ 30 khách đa phiên và ≥ 10 đa kênh có khoảnh khắc khai số; test suite ITN; WER/CER/Entity tách hai miền; PII vault | 4, 5, 6.1 |
| 2 | Kiến trúc & Harness | 22 | graph nóng có tên node; brief hiện khi gọi lại; không hỏi lại (RQR); sổ cái không ghi đè xử lý đổi ý; `guard_hard` chặn giá không từ tool; bảng fallback | 6, 7, 8, 11, 12 |
| 3 | MCP / A2A | 15 | ≥ 2 server M1 gồm `mcp-memory`; ba vai; `quote_id`; lý do chọn MCP và lý do không A2A; Command giữa agent | 15, 20 |
| 4 | Đánh giá | 15 | một lệnh in bảng; cache và manifest; `compare` từ chối so sai; baseline là công tắc; 5 chỉ số cộng kappa; `errors.jsonl` | 17, Phụ lục D |
| 5 | Cải tiến | 13 | signals → proposals → trang duyệt → version → `compare r0 r1`; rollback; unit test chống hứa liều | 18 |
| 6 | Trải nghiệm & demo | 13 | Agent Console; hai cuộc demo cộng cuộc 3; copilot và cảnh báo; ước lượng tác động từ RQR đo thật | 13, 14, 19, Phụ lục E |
| 7 | Mở rộng & chi phí | 5 | thêm ngành hàng là một file schema; thêm kênh là một dòng `identities`; chi phí tách nóng nguội trong bảng | 6.1, 17.5 |
| 8 | Trình bày & phản biện | 5 | công bố độ chính xác thước đo; nói đúng quy mô cửa duyệt; nêu chỗ gãy của thứ không làm | 17.4, 18.5, Phụ lục A |

Ba điểm trừ nặng và cái chặn: không có Session Continuity (chặn bởi `retrieve` + `render_brief` + `refresh` xong tuần 2); không có baseline (chặn bởi công tắc một bit và `compare`); số liệu không tái lập (chặn bởi cache, manifest, đồng hồ ảo).

---

# Phụ lục C · Chọn API cho LLM, embedding và trace

Số liệu dưới đây lấy từ các trang tổng hợp tháng 6 tới 9 năm 2026, không phải trang chính thức, và hạn mức free đổi vài tháng một lần. **Kiểm tra lại trang giá chính thức của từng nhà cung cấp trước khi chốt**, và ghi hạn mức đã kiểm vào README.

### Bức tranh free tier (tháng 9 năm 2026)

| Nhà cung cấp | Free tier | Hợp việc gì |
|---|---|---|
| Google AI Studio (Gemini) | Flash và Flash-Lite khoảng 10 tới 15 RPM, 250 tới 1.500 RPD tùy model; Pro đã rút khỏi free tier từ giữa 2026; embedding dùng cùng key | tiếng Việt tốt, tool calling và structured output ổn, là lựa chọn mặc định của đường nóng |
| Groq | khoảng 1.000 tới 14.400 RPD tùy model, rất nhanh, các model mở (Llama, GPT-OSS) | đường nguội khối lượng lớn: extract, gate, classifier, claim extractor; tiếng Việt kém Gemini một chút nhưng đủ cho việc có structured output |
| Mistral La Plateforme | tới 1 tỷ token mỗi tháng ở gói thử nghiệm | dự phòng đường nguội |
| Cerebras | khoảng 1 triệu token mỗi ngày | dự phòng |
| GitHub Models | 50 tới 150 RPD, 8k token vào | quá ít cho eval, chỉ để thử |
| Azure for Students | 100 USD tín dụng, 12 tháng, không cần thẻ | dự phòng có trả tiền cho ngày chạy eval |
| Langfuse Cloud Hobby | 50 nghìn đơn vị mỗi tháng, 30 ngày, 2 người dùng | đủ cho toàn dự án nếu không bật trace lúc chạy eval vòng lặp lớn |

### Chiến lược

Một lần eval đầy đủ ở M1 là khoảng 25 kịch bản × 2 tới 3 cuộc × 6 tới 8 lượt × 2 chế độ, cộng đường nguội và scorer: ước 1.500 tới 3.000 lời gọi model. Free tier 250 RPD không đủ cho một ngày eval; 1.500 RPD đủ nhưng chật. Vì thế:

1. **Đường nóng: Gemini Flash** qua `init_chat_model`, dev trên free tier, và **bật thanh toán cho một key** với ngân sách 10 tới 20 USD cho cả dự án. Flash trả tiền rẻ tới mức một lần eval đầy đủ tốn dưới một USD, và cache làm mọi lần chạy lại tốn 0.
2. **Đường nguội và scorer: Groq** với model mở có structured output, vì khối lượng lớn và không nằm trong trải nghiệm khách. Ghi rõ model nào cho việc nào trong manifest.
3. **Embedding: Gemini embedding** cùng key (đa ngôn ngữ, có tiếng Việt). Nếu chất lượng truy hồi tiếng Việt kém trên `kb_eval` thì đổi sang bge-m3 chạy local; Recall@k là cái quyết định, không phải cảm giác.
4. **Judge (QaAgent): Gemini Flash**, vì cần đọc hiểu tiếng Việt tốt nhất trong tầm giá.
5. Mọi provider đứng sau `init_chat_model` và một file cấu hình `models.yaml` (hot, cold, judge, embed). Đổi provider là đổi một dòng; manifest ghi model thật nên phép so chỉ hợp lệ khi model giống nhau.
6. Rate limit: cấu hình `max_concurrency` của runner theo RPM; retry với backoff bằng `tenacity`; cache scorer dùng chung giữa các run để không trả tiền hai lần cho cùng nhãn.

---

# Phụ lục D · Cache và manifest, thực tế là gì

Bạn hỏi đúng chỗ, vì hai thứ này là 15% của tiêu chí 4 và là cái chặn điểm trừ "số liệu không tái lập bằng code".

### Cache là gì và dùng sao

LangChain có cơ chế cache LLM sẵn: `set_llm_cache(SQLiteCache(path))` (hoặc bản Postgres). Khóa cache là băm của model, tham số sinh, và toàn bộ prompt đã serialize; trúng khóa thì trả kết quả cũ, không gọi API. Các công cụ eval phổ biến làm đúng việc này: promptfoo cache theo mặc định, deepeval có cờ cache; Langfuse thì không cache mà chỉ ghi lại. Cách làm cho bài:

- Mỗi run có file `reports/<run_id>/llm_cache.sqlite` riêng, đóng gói cùng report. `eval replay <run_id>` chạy lại toàn bộ với cache đó và không gọi API lần nào; nếu số ra khác thì có chỗ không tất định, và runner in ra chỗ đó. Đây là bằng chứng tái lập mang đi bảo vệ được.
- Scorer (classifier, claim extractor, judge) dùng một cache riêng `scorer_cache.sqlite` **dùng chung giữa các run**, vì cùng câu hỏi thì nhãn phải giống nhau bất kể vòng nào, và vì nó tiết kiệm tiền.
- Cache chỉ có tác dụng khi `temperature=0` và prompt giống hệt. Prompt khác một ký tự là miss. Đó là tính năng: **tỷ lệ trúng cache** ghi trong manifest cho biết run này là replay thật hay đã đổi prompt mà không nói.
- Cache không bật ở đường nóng của sản phẩm thật; chỉ eval runner bật.

### Manifest là gì

Một file JSON ghi mọi thứ có thể làm số đổi, sinh tự động lúc chạy:

```
run_id, run_name, timestamp, host
git: commit, dirty (có thay đổi chưa commit không)
models: {hot, cold, judge, embed}  (tên model do provider trả về, không phải tên trong cấu hình)
prompts: {tên_prompt: sha256} cho mọi file prompt và file chỉ dẫn lane
faq_version + sha256, exemplar_version, playbook_version
golden_set: sha256 của thư mục kịch bản, số kịch bản, catalog_snapshot_ids
switches: {memory, exemplars, playbook}
features: các ff.* đang bật
generation: temperature, seed, max_tokens, max_concurrency
packages: phiên bản langchain, langgraph, faster-whisper, jiwer
asr: model ASR, chuẩn hóa đã áp dụng
cache: đường dẫn, tỷ lệ trúng
metrics: bảng kết quả (để file tự đủ)
```

Cách dùng: `eval compare a b` đọc hai manifest, tính diff, và chỉ in bảng nếu diff nằm trong tập trường được phép (`switches.*`, `*_version`). Diff ở `prompts` hay `models` thì từ chối kèm thông báo "hai run này không so được, khác ở prompt X". Đây là cách biến câu "cùng bộ test, cùng model, cùng tham số" của Phụ lục A.6 thành thứ máy kiểm.

Với Langfuse: `dataset.run_experiment(run_name=..., run_metadata=manifest)` đẩy mỗi kịch bản thành một trace gắn dataset item và điểm; tab Runs của dataset cho so hai vòng cạnh nhau. Nhưng file cục bộ là nguồn sự thật, vì Hobby giữ 30 ngày và giám khảo chạy trên máy họ.

---

# Phụ lục E · Thứ tự build, ba người bốn tuần, và bậc cắt scope

Chia việc: **A** lo dữ liệu và tiếng Việt (mục 4, 5, dataset, ITN, ASR). **B** lo sổ cái, harness, MCP (mục 6 tới 15). **C** lo đánh giá, cải tiến, giao diện, trace (mục 16 tới 19). Rủi ro lớn nhất là C bị đẩy về tuần cuối; nên C bắt đầu ngay tuần 1 bằng ontology và năm file kịch bản mẫu, vì đó là hợp đồng mà A và B build dựa vào.

| Tuần | A | B | C | Cổng cuối tuần |
|---|---|---|---|---|
| 1 | schema ontology theo ngành (khi có ngành); ITN cộng test suite; ASR chạy được trên 5 file; bắt đầu sinh dataset ưu tiên khách đa phiên | bảng Postgres; `mcp-memory` và `mcp-catalog` đọc; `render_brief`; graph nóng khung với `retrieve` giả | 5 kịch bản mẫu theo 17.1; `ScriptedCustomer`; runner khung in bảng rỗng; Langfuse gắn vào | một cuộc chat đi hết graph, có brief giả, có trace |
| 2 | dataset đủ M1 (120 cuộc, 30 khách đa phiên, 10 đa kênh, 40 audio); WER lần đầu | graph nguội `extract`, `gate`, `commit`, `summarize`; `refresh`; `guard_hard`; `order.create` với `quote_id`; handoff tĩnh | 20 kịch bản; bốn bộ chấm; cache và manifest; Agent Console và timeline | **Session Continuity chạy thật: cuộc 2 mở đầu bằng xác nhận tiếp nối** |
| 3 | audio còn lại; `ff.pii_vault` | fallback đủ bảng; `compact`; `ff.policy_agent`; `ff.order_service` | **R0 với baseline, bảng số đầu tiên**; Gap Loop end to end; trang Cải tiến | **có bảng so baseline. Không có thì cắt scope chỗ khác, không lùi cổng này** |
| 4 | `ff.audio_repair` nếu còn thời gian; mô tả dataset | `ff.copilot`, `ff.kb_rag`, `ff.exemplars` | R1, R2; judge và kappa; `ff.simulator`; Dashboard; video demo; báo cáo 10 ca sai | nộp |

Bậc cắt nếu trễ, cắt từ trên xuống: `ff.reflection` và `ff.ablation` → `ff.simulator` → `ff.audio_repair` → `ff.kb_rag` (giữ FAQ phẳng) → `ff.exemplars` → `ff.copilot` (giữ handoff tĩnh) → `ff.policy_agent` → nhánh audio (giữ ≥ 20 file cho WER). **Không bao giờ cắt baseline, Session Continuity, cache và manifest.**

### Ước lượng tác động kinh doanh cho tiêu chí 6

Đề đã cho số nền: đơn lẽ ra chốt sau 2 cuộc thì mất 5 tới 10 cuộc; 40 tới 60% thời lượng cuộc gọi bị đốt để thu thập lại thông tin đã có; trung tâm 4.000 cuộc mỗi ngày. Cách dựng ước lượng bảo vệ được: lấy RQR đo thật của baseline và của hệ thống, quy ra phần thời lượng tiết kiệm mỗi cuộc, nhân với 4.000; lấy Calls-to-Close đo thật (M2) để ước phần đơn không bị mất. Nói rõ đây là ước lượng từ số của đề và số đo trên dataset sinh, không phải vận hành thật, và nêu giả định. Trung thực về hạn chế là tiêu chí chấm riêng.

---

# Phụ lục F · Câu hỏi phản biện dự kiến

| Câu hỏi | Trả lời ngắn |
|---|---|
| Orchestrator của các bạn là một câu if, sao gọi là agent? | Nó là router lai: luật cho những gì có sẵn trong state, model cho khi cần hiểu ý khách. Tách ra để lượt định tuyến không phải nạp toàn bộ ngữ cảnh vào model lớn, và để định tuyến tái lập được. Nó chuyển giao bằng `Command`, không phải gọi hàm. |
| Context & Memory Agent theo đề phải dựng Call Brief, sao chỗ đó là code? | `render_brief` là hàm thuần trong module của MemoryAgent, harness gọi nó. Về sở hữu thì MemoryAgent dựng brief; nó không tốn lượt gọi model vì brief là hàm của fact, và điều đó là lý do nạp brief dưới 5 giây. Phán đoán duy nhất về bộ nhớ là ghi gì, và đó là graph nguội. |
| Baseline có đúng chỉ khác một biến không? | Một bit ở `retrieve`. Đường nguội vẫn chạy. `compare` từ chối nếu manifest khác ở chỗ khác. |
| Bộ phân loại câu hỏi dùng LLM thì số có tái lập không? | Có, vì `temperature=0` và cache scorer dùng chung; replay ra đúng số. Và chúng tôi công bố độ chính xác của nó trên 50 câu gán tay. |
| Sao không A2A? | Mục 15.4, bốn lý do; lý do chính là A2A giả định không chia sẻ state, mà chia sẻ state là thứ chúng tôi muốn chứng minh. |
| Copilot thì KPI số 1 tính sao? | Eval chạy mode speak. Copilot là giá trị khác của tham số ở node cuối. |
| Cải tiến của các bạn có phải là học thuộc golden set không? | Gap tìm từ kho hội thoại và simulator, ca mới vào growth set, golden đóng băng và chỉ để đo. |
| Làm sao biết cải tiến nào có hại? | Ablation theo mục playbook và cụm exemplar, delta âm thì thu hồi; rollback là đổi con trỏ version. |
| Chống hứa liều bằng gì? | `policy_clean` ở cửa bank, `schema + policy check` ở cửa playbook, và một unit test gieo sẵn ca hứa sai. |
| Giá lấy từ đâu, chắc không bịa? | `quote_id` từ tool, `guard_hard` đối chiếu mọi con số với `tool_results` lượt này, `order.create` nhận `quote_id` nên server áp giá. Ba tầng. |
| PII có ra ngoài không? | Tokenize trước khi gửi model và trước khi ghi Langfuse; detokenize sau guard và chỉ khách đang nói. Xóa khách là xóa vault. |
| Hai người chung một số? | Không làm; nó phá giả định một số một khách nằm trong định dạng file test và kéo theo đổi cách tính cả năm chỉ số. Dữ liệu không chặn vì merge chỉ sửa con trỏ. |

---

# Phụ lục G · Những gì đổi so với bản trước

| Đã đổi | Thành | Vì sao |
|---|---|---|
| `JudgeAgent` riêng | gộp vào `QaAgent` | đề định nghĩa QA/Evaluator Agent là judge; Reflection thành prompt thứ hai gần như miễn phí; bớt một agent phải bảo vệ |
| bốn "Worker" | node trong subgraph của agent sở hữu | giám khảo đếm 11 thứ có tên sẽ hỏi |
| copilot ngoài phạm vi | mode thứ ba của `respond`, nối với handoff | copilot không thay chế độ tự chủ; loại nó là mất nguồn feedback 👍/👎 và làm handoff thành ngõ cụt |
| handoff là bản tĩnh | chuyển mode + `interrupt` + Nhận máy, cùng thread | Case 3 và copilot M2 chung một cơ chế |
| cảnh báo là tính năng riêng | bề mặt của `violations` của PolicyAgent | không thêm agent |
| "ít nhất hai lượt gọi model" | 1 tới N lần cùng node | đúng cách LangGraph làm tool calling; câu đệm chỉ khi có tool call |
| classifier "tuyệt đối không LLM" | LLM `temperature=0` có cache, công bố độ chính xác | luật tiếng Việt sẽ gãy; tái lập đến từ cache |
| nén ngữ cảnh là bài toán quy mô | node `compact` M2 | nằm trong dòng "phải trình bày và bảo vệ được" và rẻ |
| giá là fact dạng số | sự kiện `quote_id` có hạn, `order.create(quote_id)` | chống bịa giá ở tầng tool, ca hết hạn thành tất định |
| phía khách trong eval M1 chưa nói | `ScriptedCustomer` theo `customer_script` | không có nó thì không chạy được kịch bản |
| ma trận tài nguyên rải rác | bảng 3.3 cộng ba lớp thi hành | bạn yêu cầu, và nó là câu trả lời cho "agent có chia sẻ state thật không" |
| `pricing.get_quote`, `schedule.callback` ở M2 | kéo lên M1 | trục chống bịa giá và assertion TSR |
| cửa duyệt, gom cụm, reflection | giữ như bản trước, mô tả đúng quy mô | không có lý do đổi |
| A2A | không dùng, ghi lý do ở 15.4 | bạn đồng ý |
| trace | Langfuse, Cloud Hobby mặc định, self-host là profile | self-host v3 cần sáu container |
| lưu trữ | Postgres thật, compose, chế độ một tiến trình cho M1 | bạn muốn setup thật để trace và deploy |
| M1 → M2 | bảng feature flag Phụ lục A | không kịp vẫn đủ M1, muốn thêm không phải đập |
