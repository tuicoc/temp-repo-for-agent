# Tool-Call Accuracy labels cho `output (1)`

Nguồn bất biến: `output (1)/scenarios/*.json`. Nguồn đang chạy: `datasets/output1-btc-diagnostic-v2/scenarios/*.json`. `product.prepare()` tạo 24 file `inputs/expected-tools/<config>/<scenario>/<call>.json` cho 12 cuộc gọi × 2 cấu hình. Cả full và baseline dùng cùng kỳ vọng nghiệp vụ; chỉ khác cấu hình bộ nhớ. Không sửa dataset BTC, nguồn `output (1)` hoặc run lịch sử.

| Scenario | Call | Tool bắt buộc theo `success_if` |
| --- | --- | --- |
| SCN-GEN-0001 | call_1 | `pricing.get_quote(sku=SKU-AP-X)` |
| SCN-GEN-0001 | call_2 | `order.status(order_id=OD188213)` |
| SCN-GEN-0002 | call_1 | `pricing.get_quote(sku=SKU-MB-PUMP1)` |
| SCN-GEN-0002 | call_2 | `order.status(order_id=OD301177)` |
| SCN-GEN-0003 | call_1 | `inventory.check(sku=SKU-AP-Y)` |
| SCN-GEN-0003 | call_2–3 | Không có tool bắt buộc vô điều kiện |
| SCN-GEN-0004 | call_1–3 | Không có tool bắt buộc vô điều kiện |
| SCN-GEN-0005 | call_1–2 | Không có tool bắt buộc vô điều kiện |

Quyết định nhãn: chỉ chuyển `success_if.tool_called` + `args_match` thành positive label. Call không có positive label không có nghĩa là “không được gọi tool”; `must_not_call_tools` vẫn do kiểm tra hành vi riêng xử lý. Read-only tool ngoài nhãn được phép, vì có thể là bước tìm kiếm hợp lệ; lỗi nghiệp vụ của tool được báo riêng. Vì vậy TCA không đo được false positive của read-only tool trong các call này, và có thể là `UNDEFINED` nếu không có positive/negative nào. TCA chấm theo **toàn cuộc gọi**, kể cả tool chạy ở turn sau.

Đây là nhãn diagnostic dẫn xuất tự động, không phải bộ ground truth BTC được QA độc lập duyệt. Người duyệt: chưa có; quyết định: pending independent QA. Bằng chứng là `success_if` của 5 scenario v2 và nguồn `output (1)` tương ứng. Trước khi dùng số TCA làm kết quả chính thức, QA cần xem từng kỳ vọng, đặc biệt các tool phụ thuộc điều kiện như xác minh danh tính, rồi ghi quyết định duyệt theo [skill ground-truth-review](../datasets/ground-truth-review/SKILL.md). `prepare()` từ chối chạy nếu `success_if` positive đã thay đổi mà bảng nhãn chưa cập nhật.
