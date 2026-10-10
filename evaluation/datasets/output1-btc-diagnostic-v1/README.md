# Output (1) — BTC diagnostic revision v1

Nguồn bất biến: `../../output (1)/scenarios/`. `conversion-report.json` ghi SHA-256 nguồn,
điều kiện/field cũ và mới, cùng trạng thái **12/12 GT do nhóm diễn giải, chưa QA duyệt**.
Không sửa trực tiếp 5 scenario sau khi đã pin vào run; mọi chỉnh nhãn tạo revision mới.

Đợt này chỉ dùng JSON của 5 scenario, 12 call và 32 lượt khách cho kiểm tích hợp
M1/M2. Chưa dùng WAV/ASR, 60 câu RAG hay judgments sinh cùng dữ liệu nguồn.
`expected_outcome=khac` chỉ ánh xạ outcome ngoài enum khi không có chứng cứ chốt đơn.

- `reply_matches_any` cũ chứa lời khách và scorer BTC bỏ qua; đổi thành điều kiện
  tool hoặc câu Agent cần nói. Không có trace thì mọi `success_if` mới đều không PASS.
- SCN-GEN-0003 không có đơn đã xác thực trong CRM; mã `ORD-SCN-*` bị loại khỏi GT.
  Các ca hỏi trạng thái không còn bị chấm thành đơn đã hoàn tất.
- SCN-GEN-0004/0005 chung số điện thoại cho C034/C035, chưa có lượt xác minh;
  điều kiện diagnostic yêu cầu xác nhận và cấm đọc/tạo đơn trước khi định danh.
- SCN-GEN-0001/call_2 bỏ giá 4,49 triệu khỏi GT của SKU 2024: BTC mock báo
  4,29 triệu cho SKU cũ; không dùng giá SKU hiện hành khác để chấm HR.
- `must_carry_over`/`must_not_ask` chỉ dùng slot có GT hợp lệ, không ép đọc
  thông tin riêng của hồ sơ chưa xác minh. Cohort CCR/RQR rất nhỏ.

Đầu vào hai config từng được pin trong run local `integration/output1-diagnostic-prepared-20261010-01/`,
nhưng run/evidence không kèm trong nhánh source-only này. Preflight khi đó có 12 call/64
expected trace IDs cho full/baseline; **chưa có trace, extraction, score hoặc model run**.
Chuẩn bị bundle/run mới sau khi product bridge được port; không lấy preflight cũ làm acceptance.

Tạo revision mới bằng `evaluation/asr/.venv/bin/python -B evaluation/normalize_output1.py`
khi đích chưa tồn tại. Đổi nhãn cần sửa mapping, tăng version/đích, chạy test
và chuẩn bị bundle mới; không overwrite revision đã dùng.
