// Mock data for the staff pages that have no backend yet. Every number here
// is invented to show the shape of the page, and the pages say so with a
// "mock" badge. The shapes follow docs/flow.md: the manifest of Appendix D,
// the metric table of the brief's Appendix A.6, the scenario file of 17.1.

export const manifest = {
  run_id: 'r1-20260918-1420',
  run_name: 'R1 · faq v1',
  git: { commit: '5a1c8ee', dirty: true },
  models: {
    hot: 'gemini-3.5-flash-lite',
    cold: 'llama-3.3-70b-versatile (groq)',
    judge: 'gemini-3.5-flash',
    embed: 'gemini-embedding-001',
  },
  prompts: { advisor: 'sha256:4f1c…9a2e', route: 'sha256:88d0…13bb', extractor: 'sha256:c2a7…40f1' },
  versions: { faq: 'v1', exemplars: '—', playbook: '—' },
  switches: { memory: 'both', exemplars: false, playbook: false },
  golden_set: { scenarios: 22, sha256: 'sha256:0be4…77c9', catalog_snapshot: 'cat-2026-09-15' },
  generation: { temperature: 0, max_concurrency: 3 },
  cache: { hit_rate: 0.94, path: 'reports/r1-20260918-1420/llm_cache.sqlite' },
}

export const metrics = [
  { metric: 'Repeat-Question Rate ★', baseline: '58.3%', system: '21.4%', delta: '−63.3% relative', star: true },
  { metric: 'Context Carryover Rate', baseline: '12.5%', system: '78.9%', delta: '+66.4 pts' },
  { metric: 'Task Success Rate', baseline: '45.5%', system: '77.3%', delta: '+31.8 pts' },
  { metric: 'Hallucination Rate (price & promo)', baseline: '9.1%', system: '1.8%', delta: '−7.3 pts' },
  { metric: 'WER / CER · entity accuracy', baseline: '18.4% / 9.7% · 91.2%', system: 'same', delta: 'ASR is shared' },
  { metric: 'Average turns per scenario', baseline: '8.6', system: '5.9', delta: '−2.7' },
]

export const rounds = [
  { metric: 'RQR', r0: '24.1%', r1: '21.4%', r2: '—' },
  { metric: 'CCR', r0: '74.0%', r1: '78.9%', r2: '—' },
  { metric: 'TSR', r0: '72.7%', r1: '77.3%', r2: '—' },
  { metric: 'HR (price)', r0: '2.3%', r1: '1.8%', r2: '—' },
]

export const latency = [
  { label: 'ttft p50 / p95', value: '0.41 s / 0.92 s', hint: 'to the filler, or to content when no tool' },
  { label: 'ttft_content p50 / p95', value: '2.8 s / 6.4 s', hint: 'to a reply the guard passed' },
  { label: 'Brief load p50 / p95', value: '0.9 s / 1.7 s', hint: 'budget ≤ 5 s at M1' },
  { label: 'Cost per call · hot / cold', value: '$0.0031 / $0.0018', hint: 'tokens × list price, from the ledger' },
]

export const failedCases = [
  { id: 'SC-07', call_id: 41, metric: 'RQR', reason: 'Asked room size again on call 2 (slot room_area_m2 was in profile)' },
  { id: 'SC-11', call_id: 52, metric: 'HR', reason: 'Quoted 4.890.000 after Q-1071 expired; guard regex missed "4tr890"' },
  { id: 'SC-14', call_id: 58, metric: 'TSR', reason: 'order.create never called; customer accepted but agent asked for address first' },
  { id: 'SC-19', call_id: 66, metric: 'CCR', reason: 'Blocker "hỏi chồng" not carried over; opening skipped it' },
]

export const compareRefusal =
  'eval compare r0 r1: refused. Manifests differ outside the permitted fields: prompts.advisor (sha256:4f1c…9a2e ≠ sha256:2d90…c41a). Re-run r1 with the r0 prompt, or compare r1 against a run that shares it.'

export const qaCalls = [
  {
    id: 41,
    scenario: 'SC-07',
    customer: '…0111',
    channel: 'hotline',
    tags: ['multi-session', 'blocker'],
    turns: [
      { id: 1, speaker: 'agent', content: 'Dạ em chào chị Hoa, hôm 12/03 bên em có tư vấn chị mẫu máy lọc X cho phòng 25m² giá 4.890.000đ. Chị đã trao đổi với anh nhà chưa ạ?', detail: {
        used_brief_lines: ['B1', 'B2', 'B4'],
        tool_calls: [{ name: 'catalog_pricing_get_quote', args: { quote_id: 'Q-1071' }, result: '{"ok":true,"data":{"quote_id":"Q-1071","valid":true,"total_vnd":4890000,...}}' }],
        guard: { hard: 'pass', soft: 'not run (M2)', blocked_draft: null },
        trace: { prompt: 'HARD_RULES + context: CẢNH BÁO: none · Lane: CONTINUITY · Tier: VERIFIED · Call Brief B1..B4 · phase: opening', reply_tokens: 74, prompt_tokens: 1412, latency_ms: 2740, cost_usd: 0.00041, langfuse: 'https://cloud.langfuse.com/project/…/traces/7a1c' },
        rubric: [
          { id: 'open_confirms', label: 'Opens with a continuity confirmation', machine: true },
          { id: 'no_open_question', label: 'No open question about a known slot', machine: true },
          { id: 'price_from_tool', label: 'Price and product come from this turn\'s tool results', machine: true },
          { id: 'blocker', label: 'Addresses the carried-over blocker', machine: true },
          { id: 'tone', label: 'Tone: Vietnamese telesales register', machine: true },
        ],
      } },
      { id: 2, speaker: 'customer', content: 'Rồi em, anh ấy bảo lấy. Mà phòng chị bao nhiêu mét nhỉ em nhắc lại?' },
      { id: 3, speaker: 'agent', content: 'Dạ phòng của chị là 25m² ạ. Em xin phép tạo đơn theo báo giá Q-1071 cho chị nhé, giao về địa chỉ hôm trước chị cho ạ?', detail: {
        used_brief_lines: ['B3'],
        tool_calls: [],
        guard: { hard: 'blocked once → regenerated', soft: 'not run (M2)', blocked_draft: 'Dạ phòng chị 25m², giá 4.890.000đ, em tạo đơn luôn nhé — số "4.890.000" not in this turn\'s tool results' },
        trace: { prompt: 'HARD_RULES + context · block_reasons: ["số 4.890.000 không có trong tool"]', reply_tokens: 58, prompt_tokens: 1530, latency_ms: 4120, cost_usd: 0.00047, langfuse: 'https://cloud.langfuse.com/project/…/traces/7a1d' },
        rubric: [
          { id: 'no_open_question', label: 'No open question about a known slot', machine: true },
          { id: 'price_from_tool', label: 'Price and product come from this turn\'s tool results', machine: true },
          { id: 'closes', label: 'Moves to order.create with quote_id', machine: false },
          { id: 'tone', label: 'Tone: Vietnamese telesales register', machine: true },
        ],
      } },
      { id: 4, speaker: 'customer', content: 'Ừ em tạo đi.' },
      { id: 5, speaker: 'agent', content: 'Dạ em đã tạo đơn DH-20931 cho chị theo báo giá Q-1071, giao trong 2 ngày ạ. Cảm ơn chị!', detail: {
        used_brief_lines: [],
        tool_calls: [{ name: 'crm_order_create', args: { quote_id: 'Q-1071', address_token: '<ADDR_1>', cod: true }, result: '{"ok":true,"data":{"order_id":"DH-20931","status":"created","delivery_days":2}}' }],
        guard: { hard: 'pass', soft: 'not run (M2)', blocked_draft: null },
        trace: { prompt: 'HARD_RULES + context', reply_tokens: 44, prompt_tokens: 1688, latency_ms: 3050, cost_usd: 0.00044, langfuse: 'https://cloud.langfuse.com/project/…/traces/7a1e' },
        rubric: [
          { id: 'order', label: 'order.create called with the quote id', machine: true },
          { id: 'delivery_from_tool', label: 'Delivery time comes from the tool', machine: true },
          { id: 'tone', label: 'Tone: Vietnamese telesales register', machine: true },
        ],
      } },
    ],
  },
  {
    id: 52,
    scenario: 'SC-11',
    customer: '…4402',
    channel: 'zalo',
    tags: ['expired-promo', 'hard-case'],
    turns: [
      { id: 1, speaker: 'customer', content: 'Hôm trước em báo chị 4tr890 có tặng bộ lọc, giờ chị lấy giá đó nhé.' },
      { id: 2, speaker: 'agent', content: 'Dạ báo giá hôm trước của chị đã hết hạn ngày 16/03 ạ. Giá hiện tại là 5.200.000đ, khuyến mãi mới GIFT-2 tặng bộ lọc, chị xem giúp em ạ.', detail: {
        used_brief_lines: ['B2'],
        tool_calls: [{ name: 'catalog_pricing_get_quote', args: { quote_id: 'Q-0993' }, result: '{"ok":false,"error":{"code":"EXPIRED_QUOTE","details":{"new_quote":{"quote_id":"Q-1204","total_vnd":5200000}}}}' }],
        guard: { hard: 'pass', soft: 'not run (M2)', blocked_draft: null },
        trace: { prompt: 'HARD_RULES + context · CẢNH BÁO: Q-0993 đã hết hạn…', reply_tokens: 66, prompt_tokens: 1390, latency_ms: 3380, cost_usd: 0.00040, langfuse: 'https://cloud.langfuse.com/project/…/traces/7b02' },
        rubric: [
          { id: 'admits_expiry', label: 'States that the old quote expired', machine: true },
          { id: 'new_price_from_tool', label: 'New price comes from the tool', machine: true },
          { id: 'no_old_price', label: 'Does not repeat the old price as current', machine: true },
        ],
      } },
    ],
  },
]

export const customers = [
  { id: 'C-0001', last4: '0111', calls: 3, channels: ['hotline', 'zalo'], persona: 'Khách do dự, hỏi người nhà', last: '18/09/2026', outcome: 'chốt đơn' },
  { id: 'C-0002', last4: '4402', calls: 2, channels: ['zalo'], persona: 'Khách so giá', last: '17/09/2026', outcome: 'hẹn gọi lại' },
  { id: 'C-0003', last4: '7788', calls: 2, channels: ['facebook', 'hotline'], persona: 'Khách đã mua, đổi size', last: '16/09/2026', outcome: 'bàn giao' },
  { id: 'C-0004', last4: '2310', calls: 2, channels: ['hotline'], persona: 'Khách do dự', last: '15/09/2026', outcome: 'từ chối' },
  { id: 'C-0005', last4: '9034', calls: 1, channels: ['web'], persona: 'Khách so giá', last: '18/09/2026', outcome: 'hẹn gọi lại' },
]

export const transcripts = [
  { id: 'T-0117', customer: 'C-0001', call: 1, channel: 'hotline', persona: 'do dự', tags: ['blocker'], audio: true, region: 'Bắc',
    raw: 'dạ em tư vấn chị mẫu này giá bốn triệu tám trăm chín mươi nghìn ạ, hai trăm bốn chín k là bộ lọc thay',
    normalised: 'Dạ em tư vấn chị mẫu này giá 4.890.000 ạ, 249.000 là bộ lọc thay' },
  { id: 'T-0118', customer: 'C-0001', call: 2, channel: 'zalo', persona: 'do dự', tags: ['multi-session'], audio: false, region: '—',
    raw: 'sp nay co ship cod k a, sdt cua chi la 0982 000 111',
    normalised: 'Sản phẩm này có ship COD không ạ, số điện thoại của chị là 0982000111' },
  { id: 'T-0131', customer: 'C-0002', call: 2, channel: 'zalo', persona: 'so giá', tags: ['expired-promo', 'hard-case'], audio: true, region: 'Nam',
    raw: 'hôm trước em báo chị bốn triệu tám chín mà',
    normalised: 'Hôm trước em báo chị 4.890.000 mà' },
]

export const asrRows = [
  { region: 'Bắc', files: 11, wer: '16.2%', cer: '8.1%', entity_money: '93.5%', entity_phone: '95.0%' },
  { region: 'Nam', files: 9, wer: '21.0%', cer: '11.6%', entity_money: '88.4%', entity_phone: '91.7%' },
  { region: 'Cả hai', files: 20, wer: '18.4%', cer: '9.7%', entity_money: '91.2%', entity_phone: '93.5%' },
]

export const itnTests = [
  { spoken: 'bốn triệu tám', expected: '4.800.000', got: '4.800.000', ok: true },
  { spoken: 'bốn triệu tám trăm chín mươi', expected: '4.890.000', got: '4.890.000', ok: true },
  { spoken: 'hai trăm bốn chín k', expected: '249.000', got: '249.000', ok: true },
  { spoken: 'một củ hai', expected: '1.200.000', got: '1.200.000', ok: true },
  { spoken: 'không chín tám hai không không không một một một', expected: '0982000111', got: '0982000111', ok: true },
  { spoken: 'thứ tư tuần sau', expected: '23/09/2026 (now = 18/09)', got: '23/09/2026', ok: true },
  { spoken: 'bốn tám chín', expected: 'ambiguous → ask', got: '489', ok: false },
]

export const catalogue = [
  { sku: 'AP-XM-4L', name: 'Xiaomi Smart Air Purifier 4 Lite', price: '2.990.000', promo: 'GIFT-FILTER −300.000 đến 16/10', stock: 'white 14' },
  { sku: 'AP-SH-FP-J40', name: 'Sharp FP-J40E', price: '3.290.000', promo: 'SHARP-FAMILY −250.000 đến 31/10', stock: 'white 12 · black 7' },
  { sku: 'AP-PH-AC1215', name: 'Philips AC1215/20', price: '4.290.000', promo: 'PHILIPS-FALL −400.000 đến 20/10', stock: 'white 10' },
  { sku: 'AP-CW-AP1512', name: 'Coway AP-1512HH Mighty', price: '5.490.000', promo: 'COWAY-SEP −450.000 đến 30/09', stock: 'white 9 · black 6' },
  { sku: 'AP-DK-MC55', name: 'Daikin MC55UVM6', price: '6.290.000', promo: 'DAIKIN-CLEAN −600.000 đến 10/10', stock: 'white 6' },
  { sku: 'AP-XM-4P', name: 'Xiaomi Smart Air Purifier 4 Pro', price: '5.490.000', promo: 'PRO-SEP hết hạn 10/09', stock: 'white 6' },
]

export const proposals = [
  { id: 'P-014', cluster: 'Đang cho con bú dùng được không', count: 7, examples: ['đang cho con bú dùng được không em', 'nhà có em bé sơ sinh để máy trong phòng ngủ ổn không'], draft: 'Máy lọc không khí không phát ra chất gây hại và dùng được trong phòng có trẻ sơ sinh; nên đặt cách nôi 1–2 m và để chế độ ngủ. Với thắc mắc y tế, cửa hàng không tư vấn thay bác sĩ.', status: 'pending', source: 'corpus' },
  { id: 'P-015', cluster: 'Bảo hành bao lâu, đổi trả thế nào', count: 5, examples: ['bảo hành mấy năm', 'lỗi thì đổi máy mới hay sửa'], draft: 'Bảo hành chính hãng 12 tháng; đổi mới trong 7 ngày nếu lỗi nhà sản xuất; sau đó sửa tại trung tâm bảo hành của hãng.', status: 'pending', source: 'simulator' },
  { id: 'P-012', cluster: 'Tiền điện một tháng', count: 4, examples: ['chạy cả ngày tốn điện không'], draft: 'Công suất 30–60 W; chạy 24/24 tốn khoảng 25.000–45.000 đ/tháng tùy mẫu.', status: 'approved', source: 'corpus' },
]

export const faqVersions = [
  { version: 'v1', approved_by: 'qa@team11', at: '18/09/2026 14:02', active: true, entries: 12 },
  { version: 'v0', approved_by: 'seed', at: '15/09/2026 09:00', active: false, entries: 9 },
]

export const faqEntries = [
  { id: 'E-04', topic: 'Tiền điện', question: 'Chạy cả ngày có tốn điện không?', answer: 'Công suất 30–60 W; chạy 24/24 tốn khoảng 25.000–45.000 đ/tháng tùy mẫu.', version: 'v1' },
  { id: 'E-01', topic: 'Đổi trả', question: 'Đổi trả thế nào?', answer: 'Đổi mới trong 7 ngày nếu lỗi nhà sản xuất, còn nguyên hộp và phụ kiện.', version: 'v0' },
  { id: 'E-02', topic: 'Bảo hành', question: 'Bảo hành bao lâu?', answer: 'Bảo hành chính hãng 12 tháng tại trung tâm bảo hành của hãng.', version: 'v0' },
  { id: 'E-03', topic: 'Giao hàng', question: 'Giao hàng mất bao lâu, có thanh toán khi nhận không?', answer: 'Nội thành 1–2 ngày, tỉnh 2–4 ngày. Phí ship theo biểu giá đơn vị vận chuyển; có COD.', version: 'v0' },
]

export const faqActive = `## Chính sách đổi trả
Đổi mới trong 7 ngày nếu lỗi nhà sản xuất, còn nguyên hộp và phụ kiện.

## Bảo hành
Bảo hành chính hãng 12 tháng tại trung tâm bảo hành của hãng.

## Giao hàng
Nội thành 1–2 ngày, tỉnh 2–4 ngày. Phí ship theo biểu giá đơn vị vận chuyển; có COD.

## Tiền điện (v1)
Công suất 30–60 W; chạy 24/24 tốn khoảng 25.000–45.000 đ/tháng tùy mẫu.`

export const faqDiff = [
  { kind: 'ctx', text: '## Giao hàng' },
  { kind: 'ctx', text: 'Nội thành 1–2 ngày, tỉnh 2–4 ngày. Phí ship theo biểu giá đơn vị vận chuyển; có COD.' },
  { kind: 'add', text: '## Tiền điện (v1)' },
  { kind: 'add', text: 'Công suất 30–60 W; chạy 24/24 tốn khoảng 25.000–45.000 đ/tháng tùy mẫu.' },
]

export const feedback = [
  { id: 'F-201', type: 'thumbs_down', call: 41, turn: 3, text: 'Consultant edited: removed the address question, went straight to order.create', at: '18/09 14:11' },
  { id: 'F-198', type: 'note', call: 52, turn: 2, text: 'Good handling of expired promo; keep as exemplar candidate', at: '17/09 16:40' },
  { id: 'F-195', type: 'signal', call: 47, turn: 4, text: 'oos_early: "đang cho con bú dùng được không"', at: '17/09 11:05' },
  { id: 'F-190', type: 'signal', call: 39, turn: 2, text: 'customer repeated themselves: room size asked twice', at: '16/09 09:52' },
]

export const callbacks = [
  { id: 'CB-31', customer: '…0111', due: 'Today 15:30', reason: 'Khách hẹn hỏi chồng, gọi lại chốt', channel: 'hotline', brief: ['Đã tư vấn Xiaomi 4 Lite theo Q-449A22: 2.690.000 đ, giữ đến 25/09.', 'Rào cản: chờ hỏi chồng.', 'Việc cần làm: xác nhận và tạo đơn theo Q-449A22.'] },
  { id: 'CB-29', customer: '…4402', due: 'Today 16:00', reason: 'Báo giá cũ hết hạn, khách muốn giá mới', channel: 'zalo', brief: ['Q-0993 hết hạn 16/03; giá hiện tại 5.200.000 đ theo Q-1204.', 'Khách so giá với bên khác 4.950.000 đ.', 'Việc cần làm: nêu khuyến mãi GIFT-2, không hứa giảm thêm.'] },
  { id: 'CB-27', customer: '…7788', due: 'Tomorrow 09:00', reason: 'Đổi size, chờ kho xác nhận', channel: 'facebook', brief: ['Đơn DH-20877 đã tạo 14/09, giao 16/09.', 'Khách muốn đổi màu trắng sang đen.', 'Việc cần làm: xác nhận tồn kho đen rồi cập nhật đơn.'] },
]

export const handoffs = [
  { id: 'H-08', call_id: 47, customer: '…0111', reason: 'Câu hỏi ngoài phạm vi: "đang cho con bú dùng được không"', status: 'pending', at: '14:07', brief: ['Khách VERIFIED, 3 lần liên hệ.', 'Đã tư vấn Xiaomi 4 Lite theo Q-449A22.', 'Câu chưa trả lời được: dùng khi đang cho con bú.', 'Ba lượt cuối: khách hỏi, agent thừa nhận không có thông tin, đề nghị chuyển người.'] },
]

export const copilotSuggestion = {
  text: 'Dạ chị ơi, về việc dùng máy khi đang cho con bú thì em không phải bác sĩ nên không dám khẳng định ạ. Máy chỉ lọc bụi và không phát ra chất gì, nhưng chị hỏi thêm bác sĩ cho yên tâm nhé. Chị có muốn em giữ báo giá Q-449A22 tới 25/09 không ạ?',
  warnings: [],
  used_brief_lines: ['B2', 'B4'],
}
