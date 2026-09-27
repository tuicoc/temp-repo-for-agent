# Lab Jev: thông số, setup, và trạng thái

Tạm dừng ngày 23/09/2026. Jev chưa nối vào luồng chính nào: `route` vẫn là
stub, API vẫn chạy đường cũ trong `api/calls.py`. Báo cáo đầy đủ:
`workbench/reports/jev/jev-bench.html`, bản trên claude.ai
https://claude.ai/artifact/U9WM9FUSoMMgbdiH5i1y2M. Tóm tắt kết quả cũng ở mục
8.5 của `docs/architecture-notes.md`.

## Setup đã xong

| Thứ | Trạng thái |
|---|---|
| Key `AI_GATEWAY_API_KEY` | trong `backend/.env` |
| Thẻ trên team Vercel | đã gắn; trước đó mọi lời gọi báo `customer_verification_required` |
| Gói Vercel | Hobby: **không có Zero Data Retention** (`permission_denied`, chỉ Pro và Enterprise) |
| `config/models.yaml` | khối `evaluation_providers.vercel_gateway` (`zero_data_retention: false`) và `evaluators.orchestrator` (Jev, timeout 1 giây) |
| Client | `src/llm/jev.py`: `POST /v1/evaluate`, limiter chung, không chờ, không thử lại, lỗi là `JevUnavailable(code)`; có `timeout` tuỳ chọn cho đo đạc |
| Agent | `BaseAgent.evaluate()` gọi evaluator theo tên agent; `OrchestratorAgent.route` chưa làm |
| Câu hỏi | `src/components/orchestration/questions.py`: `INTENT`, `WANTS_HUMAN`, viết tiếng Anh |
| Lab AI SDK | `workbench/lab/gateway/`: `ai@7.0.112`, `.env.local` có key, `index.ts` gọi `openai/gpt-5.5`. Chạy lúc chưa có thẻ nên lỗi 403, **chưa chạy lại** |

## Thông số chạy được

**Jev**

- Trung vị 0,6 giây mỗi lời gọi với câu ngắn (khoảng 400 đến 700 token vào),
  0,83 giây với 25 đoạn FAQ (khoảng 3.600 token), p95 dưới 1,6 giây. Đo từ
  máy ở Việt Nam; chưa đo từ Azure.
- Lời gọi đầu tiên sau khi mở kết nối từng quá 1 giây và bị timeout; các lời
  gọi sau thì không.
- Gateway gói miễn phí trả 429 sau khoảng 80 lời gọi liên tiếp (bắt chờ 42 đến
  52 giây) và 503 ở 4 trên 216 lời gọi.
- Câu hỏi viết tiếng Anh tốt hơn tiếng Việt ở định tuyến (97% so với 94%), ngang
  nhau ở policy.
- Hỏi lại cùng câu ba lần: 97% ra cùng quyết định, xác suất lệch tối đa 0,05.

**Ngưỡng theo từng câu hỏi** (chọn trên chính bộ lab, phải chọn lại trên bộ
gán nhãn riêng trước khi dùng thật):

| Câu hỏi | Ca "có" | Ca "không" cao nhất | Ngưỡng hợp lý |
|---|---|---|---|
| Đòi gặp người | 0,98 đến 0,99 | 0,29 | 0,5 trở lên đều đúng |
| Khách xác nhận | 0,93 đến 0,98 | 0,24 | 0,5 trở lên đều đúng |
| Cần tra tool | 0,17 đến 0,97 | 0,64 | khoảng 0,55, vẫn sai 3 ca |
| Vi phạm policy (từng loại) | từ 0,92 | 0,66 (nhận là người), 0,87 (P10 tranh cãi) | khoảng 0,9 |
| Hỏi lại điều đã biết | 0,78 đến 0,96 | 0,64 | khoảng 0,75 |

**Model sinh chữ dùng để so**

- `gemini-3.5-flash-lite`: phải đặt `reasoning_effort="minimal"`; để mặc định
  thì một câu phân loại mất 7,2 giây, đặt rồi còn 1,1 đến 1,8 giây.
- `openai/gpt-oss-20b` trên Groq: phải `reasoning_effort="low"` và
  `method="json_schema"`; để mặc định nó tiêu hết trần 800 token cho suy nghĩ
  và trả JSON hỏng. Free tier chỉ khoảng 6.000 token vào mỗi phút, nên câu FAQ
  một phút một câu.

## Kết quả

| Việc | Jev 0,5 / ngưỡng chỉnh | Gemini | Groq | Kết luận |
|---|---|---|---|---|
| Định tuyến | 97% / 97% | 97% | 93% | thay bằng Jev |
| Xác nhận danh tính | 100% / 100% | 100% | 100% | thay bằng Jev |
| Chính sách, chặn đúng từng câu nháp | 80% / 90% | 93% | 60% | dùng kèm |
| FAQ, đoạn đứng đầu | 87% | 93% | 87% | thay, đo thêm (BM25 cũng 93%) |
| Chấm câu hỏi lặp | 85% / 95% | 95% | 75% | chưa thay |

## Khi quay lại

1. Quyết có dùng Jev cho `route` và `resolve` không.
2. Gán một bộ nhãn riêng (khoảng 50 câu, §17.4) để chốt ngưỡng từng câu hỏi.
3. Che PII trước khi gửi cho Jev, vì gói Hobby không có Zero Data Retention.
4. Đo lại độ trễ từ máy chủ Azure.
5. Soạn bộ FAQ thật và câu hỏi khó hơn; bộ hiện tại BM25 đã đúng 93%.
6. Chạy lại lab AI SDK ở `workbench/lab/gateway/` nếu còn cần (model trả phí).

Chạy lại lab: xem `README.md` cạnh file này. Cache giữ mọi câu trả lời, nên
`run.py --score` và `report.py` không tốn lời gọi nào.
