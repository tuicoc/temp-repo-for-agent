# Sơ đồ kiến trúc

[![version](https://img.shields.io/badge/version-0.0.0-blue.svg)](README.md)

Mỗi hình độc lập, copy từng khối một. Số mục khớp với `flow.md`. Nhãn trong hình bằng tiếng Anh, chú thích bằng tiếng Việt. Hình chỉ giữ mức vừa đủ để hiểu luồng; chi tiết nằm trong `flow.md`.

Quy ước: node chữ thường là code thuần, node ghi tên Agent là nơi gọi model, nét đứt là cạnh vượt nhịp hoặc tùy chọn.

---

## 1. Toàn cảnh

### 1a. Ba nhịp

```mermaid
flowchart LR
    HOT["Hot path<br/>one turn, customer waiting"]
    COLD["Cold path<br/>after hangup, MemoryAgent"]
    LEDGER[("Ledger<br/>facts, episodes")]
    EVAL["Evaluation<br/>one command"]
    IMPROVE["Improvement<br/>weekly, human review"]

    HOT -->|"transcript"| COLD
    COLD -->|"write"| LEDGER
    LEDGER -.->|"next call, read only"| HOT
    EVAL -.->|"drives the same graph<br/>memory on / off"| HOT
    HOT -.->|"signals"| IMPROVE
    EVAL -.->|"failed cases"| IMPROVE
    IMPROVE -.->|"FAQ, exemplars, playbook"| HOT
```

Ba chu kỳ khác nhau: hội thoại theo lượt, ghi nhớ theo cuộc, học theo tuần. Vì tách rời được nên baseline chỉ là một công tắc.

### 1b. Câu chuyện hai cuộc gọi

```mermaid
sequenceDiagram
    participant C as Customer
    participant H as Hot graph
    participant T as MCP tools
    participant W as Cold worker
    participant L as Ledger

    Note over C,L: Call 1, day 1
    C->>H: "air purifier, 25m2, budget 5M"
    H->>T: catalog.search, pricing.get_quote
    T-->>H: quote Q-1071, 4,890,000, valid to Mar 16
    H-->>C: advice, price, "call back after asking husband"
    H->>W: hangup, job persist
    W->>L: extract, gate, commit facts + episode

    Note over C,L: Call 2, day 3
    C->>H: same phone number
    H->>L: resolve VERIFIED, retrieve profile
    H->>T: refresh: is Q-1071 still valid?
    T-->>H: valid, in stock
    H-->>C: continuity opening, no repeated questions
    C->>H: "ok, I'll take it"
    H->>T: order.create(quote_id = Q-1071)
    H-->>C: order confirmed
    H->>W: hangup, job persist
```

---

## 2. Kiến trúc triển khai

```mermaid
flowchart LR
    UI["ui<br/>Streamlit, 6 pages"] --> API["api<br/>FastAPI + hot graph"]
    EVAL["eval runner<br/>CLI"] --> API
    API --> MCP["MCP servers<br/>memory, catalog, crm<br/>M2: order, knowledge"]
    API --> PG[("postgres + pgvector<br/>ledger, checkpointer, jobs")]
    MCP --> PG
    WK["worker<br/>cold graph, QA graph, jobs"] --> MCP
    WK --> PG
    API -.-> LF["Langfuse<br/>cloud hobby, self-host optional"]
    WK -.-> LF
```

`make dev` cho M1: api và worker cùng một tiến trình, MCP qua stdio, chỉ Postgres trong Docker. `make up` cho M2: compose đầy đủ.

---

## 3. Trạng thái phiên và quyền

### 3a. Mỗi agent chỉ nhận một lát cắt của state

```mermaid
flowchart LR
    HS[("HotState<br/>one object, checkpointer")]
    HS -->|"tier, has brief, last message, flags"| RO["route<br/>OrchestratorAgent"]
    HS -->|"messages, brief, context pack, tool results"| AA["advisor<br/>AdvisorAgent"]
    HS -->|"draft, tool results only<br/>no brief, no history"| PA["guard_soft<br/>PolicyAgent"]
    RO -->|"lane, intent"| HS
    AA -->|"draft, tool results"| HS
    PA -->|"verdict, block reasons"| HS
```

### 3b. Ai được ghi cái gì

```mermaid
flowchart TB
    subgraph LEDGER["Ledger: facts, episodes"]
        L1["write: MemoryAgent only, cold path"]
        L2["read: harness prefetch, Advisor read tools, QA, UI"]
    end
    subgraph BIZ["Business data: quotes, orders, callbacks"]
        B1["write: Advisor via MCP tools"]
        B2["read: refresh, eval assertions"]
    end
    subgraph KNOW["Knowledge: FAQ, KB, exemplars, playbook"]
        K1["write: apply job, after human approval"]
        K2["read: budget, retrieve, Policy snippets"]
    end
    subgraph ENFORCE["Enforced at three layers"]
        E1["subgraph input schema"] --- E2["MCP client role + server check"] --- E3["Postgres roles"]
    end
```

Bảng đầy đủ ở mục 3.3 của `flow.md`.

---

## 4. L0, tiếp nhận

```mermaid
flowchart LR
    AUD["audio files<br/>offline ingest"] --> ASR["ASR<br/>faster-whisper / PhoWhisper"]
    ASR -.->|"M2"| REP["transcript repair<br/>product dictionary, diarization"]
    ASR --> NORM
    REP --> NORM
    CHAT["chat message"] --> CLEAN["text cleanup<br/>teencode, no-diacritics, mixed EN"]
    CLEAN --> NORM["normalize<br/>diacritics, ITN for money / phone / date"]
    NORM --> PII["PII tokenizer<br/>M1 regex, M2 vault"]
    PII --> OUT[/"NormalizedUtterance"/]
```

Audio và chat đi qua cùng một bộ chuẩn hóa, sau đó cùng một harness.

---

## 5. L1, danh tính

```mermaid
flowchart LR
    K["extract keys<br/>caller phone, stated phone, order code"] --> F["lookup identities<br/>HMAC hash"]
    F -->|"caller phone matches"| V["VERIFIED<br/>full brief"]
    F -->|"stated by customer, unconfirmed"| P["PROBABLE<br/>confirm questions only"]
    F -->|"no match"| U["UNKNOWN<br/>new customer"]
    P -.->|"customer confirms"| V
    P -.->|"MemoryAgent confirms, cold path"| DB[("identities")]
```

---

## 6. L2, sổ cái, nhánh đọc

```mermaid
flowchart LR
    SW{{"memory switch"}} -.-> R
    L[("ledger<br/>current facts, episodes")] --> R["retrieve<br/>via mcp-memory, read role"]
    R --> B["render_brief<br/>pure function, numbered lines"]
    B --> RF["refresh<br/>parallel tool calls:<br/>quote still valid? in stock?"]
    RF --> OUT[/"brief + freshness warnings"/]
```

Công tắc tắt thì `retrieve` trả về rỗng và mọi thứ sau đó chạy như khách mới. Đó là baseline.

---

## 7. L2, cổng ghi, đường nguội

```mermaid
flowchart LR
    J[("jobs")] --> LD["load<br/>transcript, current facts"]
    LD --> EX["extract<br/>MemoryAgent, structured output"]
    EX --> GT["gate<br/>1 classify<br/>2 cap for open notes<br/>3 format check<br/>4 conflict rule by slot type"]
    GT -->|"rejected"| DR["drop + log"]
    GT -->|"conflicts with business fact"| DS["mark disputed"]
    GT -->|"accepted"| CM["commit<br/>add, update, invalidate, skip"]
    DS --> CM
    CM --> SM["summarize<br/>one episode line"]
    SM -.->|"M2"| QA["enqueue QaAgent"]
```

Luật thắng khi mâu thuẫn:

```mermaid
flowchart LR
    C{"slot type"} -->|"preference"| P["customer wins<br/>newer beats older"]
    C -->|"business fact"| B["tool wins<br/>customer claim logged only"]
    C -->|"past event"| E["system record wins"]
```

---

## 8. L3, graph nóng

```mermaid
flowchart LR
    S(["START"]) --> PC["perceive"]
    PC -->|"call start"| RV["resolve"] --> RT["retrieve"] --> RF["refresh"] --> RO
    PC -->|"later turns"| RO
    RO["route<br/>OrchestratorAgent"] -->|"Command"| BD["budget"]
    RO -->|"Command"| HO["handoff"]
    BD --> AD["advisor<br/>AdvisorAgent"]
    AD --> GH["guard_hard"]
    GH --> GS["guard_soft<br/>PolicyAgent, M2"]
    GS --> RS["respond<br/>speak or copilot"]
    HO --> RS
    RS --> E(["END of turn"])
    GH -.->|"blocked, regen up to 2"| AD
    GS -.->|"blocked, regen up to 2"| AD
    E -.->|"hangup"| PS[("job persist")]
```

Không vẽ: `compact` (chạy trước `route` khi vượt ngưỡng token, M2), `safe_default` (khi hết trần sinh lại), `human_send` (chỉ ở copilot, xem hình 14). Đồng hồ ảo `now` nằm trong state, mọi node đọc từ đó.

---

## 9. OrchestratorAgent, node route

```mermaid
flowchart LR
    IN[/"tier, has brief,<br/>last message, flags"/] --> RULES["rules first<br/>no model call"]
    RULES -->|"needs intent"| CLS["intent classifier<br/>small model, enum, cached"]
    RULES --> LANE["lane"]
    CLS --> LANE
    LANE --> CMD["Command(goto = budget or handoff)"]
```

| Lane | When | Tools bound to Advisor |
|---|---|---|
| HANDOFF | tools down, customer asks for a human, Policy blocked twice | none |
| CLARIFY | low ASR confidence | none |
| CONFIRM_IDENTITY | tier PROBABLE | none |
| ORDER_SERVICE (M2) | order status, change size or address | order.status, order.update |
| OUT_OF_SCOPE | question with no FAQ / KB hit | none, so "no tool called" is assertable |
| CONTINUITY | VERIFIED with open blocker or valid quote | catalog, pricing, inventory, order.create, callback |
| NEW | everything else | same as CONTINUITY |

---

## 10. AdvisorAgent, subgraph

```mermaid
flowchart LR
    IN[/"context pack, brief,<br/>lane, block reasons"/] --> M["model<br/>tools bound by lane<br/>output: reply, used_brief_lines, confidence"]
    M -->|"tool calls"| T["ToolNode<br/>MCP, advisor role"]
    T --> M
    M -->|"final answer, max 3 loops"| OUT[/"draft, tool results"/]
    M -.->|"low confidence"| F["flag oos_late"]
    T -.->|"filler streamed<br/>only when a tool is called"| UI["UI"]
```

Chính sách tool: giá, khuyến mãi, tồn kho, giao hàng luôn tra tool; chính sách qua FAQ hoặc KB; thứ đã có trong brief không tra; xã giao không tra.

---

## 11. Guardrail và cảnh báo

```mermaid
flowchart LR
    D[/"draft + tool results"/] --> H["guard_hard, regex<br/>prices in tool results?<br/>no PII leak?<br/>tier allows disclosure?<br/>not claiming human?"]
    H -->|"pass"| S["guard_soft<br/>PolicyAgent, M2<br/>policy promises, tone"]
    H -->|"fail"| BL["block + reasons"]
    S -->|"fail"| BL
    S -->|"pass"| DT["detokenize<br/>own customer only"] --> R["respond"]
    BL -.->|"regen up to 2"| A["advisor"]
    BL -.->|"exhausted"| SD["safe_default"]
    S -.->|"same violations shown as warnings"| W["speak: transparency panel<br/>copilot: badge on suggestion<br/>copilot: check on human text"]
```

Cảnh báo không phải agent thứ sáu, nó là `violations` của PolicyAgent hiện ở ba chỗ.

---

## 12. Fallback

```mermaid
flowchart LR
    E{"failure"} -->|"tool error / timeout"| F1["retry once, never guess numbers,<br/>offer callback"]
    E -->|"bad ASR"| F2["ask one short question"]
    E -->|"bad model format"| F3["retry once, then safe_default"]
    E -->|"no memory found"| F4["treat as new, never pretend"]
    E -->|"disputed fact"| F5["confirm question"]
    E -->|"out of scope"| F6["ADMIT FIRST, then offer handoff"]
    F1 -.->|"repeated"| H["handoff"]
    F6 -.->|"customer agrees"| H
```

Câu nói cụ thể với khách cho từng ca ở bảng mục 12 của `flow.md`.

---

## 13. Handoff

```mermaid
sequenceDiagram
    participant R as route
    participant H as handoff node
    participant DB as handoffs table
    participant C as Customer
    participant UI as Agent Console
    participant A as Human agent
    participant W as Cold worker

    R->>H: Command(goto = handoff)
    H->>H: render_handoff(state, ledger)
    H->>DB: insert pending brief
    H->>H: mode = copilot
    H-->>C: bridging line: "connecting you to a colleague"
    H->>UI: interrupt, graph paused
    UI->>A: show brief + Accept button
    A->>UI: Accept
    UI->>H: Command(resume)
    Note over C,A: conversation continues in copilot mode, same thread
    C->>A: hangup
    A->>W: job persist, full transcript incl. human turns
```

Handoff Brief chứa: khách là ai, sản phẩm với quote_id và giá, rào cản, cam kết (M2), fact tranh chấp, 3 lượt cuối, lý do chuyển, việc cần làm, link trace. Bàn giao ca là cùng renderer chạy trên danh sách callback đến hạn.

---

## 14. Copilot

```mermaid
sequenceDiagram
    participant C as Customer
    participant G as Hot graph
    participant P as PolicyAgent
    participant UI as Agent Console
    participant A as Human agent

    C->>G: message
    G->>G: perceive, route, budget, advisor, guard_hard
    G->>P: draft + tool results
    P-->>G: verdict, violations
    G->>UI: respond(copilot): interrupt(suggestion, warnings, brief)
    UI->>A: show suggestion
    A->>UI: use as is / edit / write own
    UI->>G: Command(resume = text, action)
    G->>G: human_send: guard_hard + guard_soft on human text
    alt violations found
        G->>UI: interrupt(warning)
        A->>UI: fix, or override with reason
        UI->>G: Command(resume)
    end
    G-->>C: send human text, speaker = human_agent
    G->>G: signal thumbs up if used as is, thumbs down with diff if edited
    Note over G,A: order.create in copilot: interrupt before ToolNode for approval
```

Eval luôn chạy mode speak; copilot chỉ là giá trị khác của tham số ở node cuối.

---

## 15. L4, MCP và phân quyền

```mermaid
flowchart LR
    AA["AdvisorAgent"] -->|"role advisor"| AD["tool adapter<br/>MultiServerMCPClient per role<br/>server checks role header"]
    HP["harness prefetch<br/>resolve, retrieve, refresh"] -->|"role harness, read only"| AD
    MC["MemoryAgent, cold"] -->|"role memory_writer"| AD
    AP["apply job"] -->|"role admin"| AD
    AD --> MEM["mcp-memory"]
    AD --> CAT["mcp-catalog"]
    AD --> CRM["mcp-crm"]
    AD -.-> ORD["mcp-order, M2"]
    AD -.-> KB["mcp-knowledge, M2"]
```

| Server | Read tools | Write tools |
|---|---|---|
| mcp-memory | get_profile, get_episodes, get_open_items, identity.find, M2 search_notes | commit_facts, commit_episode, confirm_identity, link_provisional, M2 delete_customer |
| mcp-catalog | catalog.search, inventory.check, pricing.get_quote (returns quote_id, valid_until) | |
| mcp-crm | crm.get_customer | order.create(quote_id), schedule.callback |
| mcp-order (M2) | order.status | order.update |
| mcp-knowledge (M2) | kb.search | kb.upsert (admin) |

`quote_id` là trục chống bịa giá: Advisor không nhớ giá, guard chỉ đối chiếu với tool results, `order.create` nhận `quote_id` nên server áp giá. Không dùng A2A vì lý do ở mục 15.4 của `flow.md`.

---

## 16. Truy vết

```mermaid
flowchart LR
    U["agent utterance<br/>messages.meta"] -->|"used_brief_lines"| B["brief line"]
    B -->|"fact_ids"| F["fact<br/>source: call_id, turn_id"]
    F --> T[("raw transcript turn")]
    T -.-> AUD["audio file"]
    T -.-> VAULT[("PII vault")]
    U -->|"tool_call_ids"| TC["tool calls, args, results"]
    U -->|"verdicts"| GV["guard verdicts, blocked drafts"]
    U -.->|"trace_id"| LF["Langfuse trace<br/>prompts, latency, tokens<br/>session = customer"]
    QA["QA Review page<br/>click a turn, see all of the above,<br/>score with rubric"] -.-> U
```

Bảng của mình là nguồn sự thật, Langfuse là màn hình soi. Trace chỉ chứa text đã tokenize.

---

## 17. L5, đánh giá

### 17a. Runner

```mermaid
flowchart LR
    G["golden set, frozen<br/>customer_script, must_not_ask,<br/>must_carry_over, success_if"] --> RN["runner<br/>sandbox, catalog snapshot, virtual clock"]
    RN -->|"memory on"| SYS["call 1, cold path sync, call 2, call 3"]
    RN -->|"memory off"| BAS["same graph, brief = None"]
    SYS --> SC["same scorers"]
    BAS --> SC
    ASR["score_asr, 20+ files"] --> SC
    SC --> RP["table A.6 + errors.jsonl"]
    RN --> MF["manifest.json<br/>commit, models, prompt hashes,<br/>versions, switches"]
    RN --> CA[("llm_cache per run")]
    MF --> CMP["eval compare r0 r1<br/>refuses if manifests differ<br/>beyond switches / versions"]
```

### 17b. Bốn bộ chấm

```mermaid
flowchart LR
    T[/"transcript + tool log"/] --> Q["question_classifier<br/>small model, temp 0, cached,<br/>accuracy reported on 50 labels"] --> M1["RQR"]
    T --> F["fact_usage_checker<br/>deterministic"] --> M2["CCR"]
    T --> A["assertion_runner"] --> M3["TSR"]
    A -.->|"graded_by = judge"| J["QaAgent judge<br/>binary rubric, kappa vs human"] --> M3
    T --> C["claim_extractor<br/>small model, temp 0, cached"] --> M4["HR, separate for price and promo"]
```

### 17c. Phía khách trong eval

```mermaid
flowchart LR
    A["agent turn"] --> Q{"question about a slot?"}
    Q -->|"open"| ANS["answer from script"]
    Q -->|"confirm"| CF["confirm reply"]
    Q -->|"no"| NX["next scripted line,<br/>or accept offer if buy_if_offered"]
    SIM["SimulatorAgent, M2<br/>persona, script facts only,<br/>patience drops on repeated questions"] -.->|"replaces this, same scenario file"| A
```

---

## 18. L6, cải tiến

### 18a. Knowledge Gap Loop, M1

```mermaid
flowchart LR
    S["signals<br/>out of scope, customer repeats,<br/>eval errors, outcomes, thumbs"] --> CL["collect + cluster"]
    CL --> PR[("proposals")]
    PR --> HR{"review page<br/>approve / reject"}
    HR -->|"approved"| AP["apply"]
    AP --> FQ[("faq_block vN+1<br/>M2: KB")]
    AP --> GS["growth set<br/>never the golden set"]
    FQ -.->|"into prompt via budget"| ADV["advisor"]
    CORP["conversation corpus + simulator runs"] -.->|"discovery source"| S
```

### 18b. Exemplar Bank, M2

```mermaid
flowchart LR
    WON["closed-won call"] --> PC{"policy_clean?<br/>guard_soft on every turn, HR = 0"}
    PC -->|"no"| DR["reject"]
    PC -->|"yes"| HR{"review"} --> EB[("exemplars")]
    EB --> SEL["select by objection type + persona,<br/>diversify"] --> RT["retrieve, last in budget priority"]
```

### 18c. Reflection và playbook, M2

```mermaid
flowchart LR
    Q["QaAgent score"] --> W{"worth learning?<br/>lost deal, objection, OOS, disputed"}
    W -->|"no"| SK["skip"]
    W -->|"yes"| RF["reflect<br/>structured lesson"] --> CK{"schema + policy check"}
    CK -->|"fail"| DR["discard"]
    CK -->|"pass"| HR{"review"} --> PB[("playbook<br/>versioned entries")]
    PB -.->|"metrics drop"| RV["revoke entry"]
```

### 18d. Vòng và quay lui

```mermaid
flowchart LR
    R0["R0: faq v0<br/>baseline + system"] --> R1["R1: faq v1"] --> R2["R2: + exemplars + playbook, M2"] --> R3["R3: faq v2, M2"]
    R2 --> AB["ablation per entry<br/>negative delta = revoke"]
    R1 -.->|"compare drops"| RB["rollback: version pointer"]
    GOLD[("golden set, frozen<br/>same manifest except versions")] --- R0
```

---

## 19. L7, giao diện

```mermaid
flowchart LR
    CH["Chat<br/>customer view"]
    AC["Agent Console<br/>Call Brief, memory timeline,<br/>transparency panel, handoff card,<br/>copilot suggestions, thumbs"]
    QA["QA Review<br/>trace + rubric + human scoring"]
    IM["Improvement<br/>proposals, versions, rollback"]
    DB["Dashboard, M2<br/>metrics by round, latency, cost"]
    SH["Shift handover<br/>due callbacks + briefs"]
    API["api"] --> CH
    API --> AC
    API --> QA
    API --> IM
    API --> SH
    REP["reports / manifests"] -.-> DB
```

---

## 20. Tương tác giữa các agent

```mermaid
flowchart LR
    OA["OrchestratorAgent"] -->|"Command, lane"| AA["AdvisorAgent"]
    OA -->|"Command"| HO["handoff to human"]
    AA -->|"draft + tool results only"| PA["PolicyAgent, M2"]
    PA -->|"block reasons, not just pass / fail"| AA
    PA -->|"pass"| OUT(["respond"])
    OUT -->|"transcript at hangup"| MC["MemoryAgent, cold, WRITE"]
    MC -.->|"next call, read by harness,<br/>not through MemoryAgent"| AA
    MC -.-> QA["QaAgent, cold, SCORE<br/>outside the creation path"]
    ST[("one HotState")] --- OA
    ST --- AA
```

Không agent nào vừa tạo vừa tự duyệt. Giá trị của tách nằm ở chỗ agent thứ hai nhận ít thông tin hơn.

---

## 21. Kiểm kê

```mermaid
flowchart LR
    subgraph M1["M1: 3 agents"]
        A1["OrchestratorAgent"] --- A2["AdvisorAgent"] --- A3["MemoryAgent"]
    end
    subgraph M2["M2: +2"]
        A4["PolicyAgent"] --- A5["QaAgent = judge + reflect"]
    end
    subgraph EV["eval only, M2"]
        A6["SimulatorAgent"]
    end
    subgraph CODE["code nodes, no model"]
        N1["perceive, resolve, retrieve, refresh, budget,<br/>guard_hard, safe_default, respond, handoff<br/>M2: compact, human_send"]
    end
    subgraph JOBS["jobs"]
        J1["persist, collect, cluster, apply<br/>M2: rollback, ablation"]
    end
```

Slide M1 chỉ trình bày khối M1 và khối code nodes.
