# ASR Evaluation M1

**Scope 04/10/2026:** theo [README Evaluation](../README.md), audio/segments BTC đầy đủ deferred, không xin/tải/sinh/tích hợp ở lượt implementation hiện tại. ASR/audio team, ITN, coverage, human listening và inference diarization team vẫn trong scope. Các số/lệnh bên dưới là trạng thái lịch sử; không sửa artifacts để bỏ blocker hoặc gọi team audio là BTC. Scope hiện tại hoàn tất không đồng nghĩa nghiệm thu đầy đủ yêu cầu audio BTC.

Pipeline local: audio WAV → model local → transcript thô → ITN/entity v3 → scorer BTC nguyên bản → coverage, timing và error report. Ngày hẹn gọi lại chấm bổ sung riêng, không sửa metric BTC.

## Whisper-medium đã chạy thử — 03/10/2026

Đã tải `Systran/faster-whisper-medium` revision `08e178d48790749d25932bbc082711ddcfdfbc4f` vào `models/faster-whisper-medium/` (model.bin khoảng 1,4 GiB), ghim nguồn tại [model_source_medium.json](model_source_medium.json). Đây là Whisper-medium đa ngôn ngữ, **không phải PhoWhisper**. Chạy offline CPU INT8, 4 threads bằng runner hiện có; không gửi audio lên API. Không đổi mặc định Small và không chạy lại Small theo yêu cầu user.

| Chỉ số trên cùng 4 audio dev | Small cũ chấm lại ITN v3 | Medium mới |
|---|---:|---:|
| WER chuẩn hóa (%) | 6,3 | 2,3 |
| CER chuẩn hóa (%) | 5,0 | 1,0 |
| Tiền đúng | 4/4 | 4/4 |
| SĐT đúng | 0/4 | 4/4 |

[Report Medium](runs/dev-whisper-medium-v1/report.json), [so sánh cùng hash audio/GT](runs/comparison-whisper-medium-v1/comparison.md), [lock](runs/dev-whisper-medium-v1/config.lock.json). Small được lấy từ transcript lịch sử trong `dev-v4-replay`, không phải lượt chạy Small mới; replay không có timing ASR để so tốc độ.

Medium raw WER/CER là 12,6%/15,1%; sau numeric-word normalization là 2,3%/1,0%. Không trộn hai cách chấm. Tiền + phone đạt 8/8 trên fixture, không suy ra đạt production. Bộ dev có 1 file nhiễu mô phỏng; GT pending human listening, chưa có audio BTC, chưa chấm ngày hẹn (N/A). Thời gian tải model khoảng 3,39 giây; ba warm-up vẫn được chấm chất lượng, timing effective chỉ còn file thứ tư: khoảng 33,55 giây/phút audio. Đây không phải latency streaming, cũng chưa đủ sample để kết luận tốc độ ổn định.

Chạy lại Medium phải chọn thư mục output mới:

```bash
evaluation/asr/.venv/bin/python evaluation/asr/run_eval.py \
  --dataset evaluation/asr/datasets/synthetic-v1/dev \
  --model evaluation/asr/models/faster-whisper-medium \
  --expected-count 4 --profile baseline \
  --out evaluation/asr/runs/dev-whisper-medium-next
```

Sau dev đã chạy 20 eval theo yêu cầu user, với cùng lock (xem bên dưới). Không thay GT hoặc chọn lại cấu hình theo eval. 13 unit tests đạt; checkpoint được tải thành công và hash từng file nằm trong manifest/lock của run.

### Eval Medium đã hoàn tất — 03/10/2026

[Report 20 audio](runs/eval-whisper-medium-v1/report.json), [bảng so Small lịch sử](runs/comparison-eval-whisper-medium-v1/comparison.md), [lỗi cần nghe](runs/eval-whisper-medium-v1/errors.json). Coverage 20/20, không thiếu/thừa hypothesis, lock eval giống hệt lock dev. Small không chạy lại: so với transcript lịch sử được chấm lại bằng ITN v3, cùng hash audio/GT.

| Chỉ số | Small lịch sử | Medium eval |
|---|---:|---:|
| WER chuẩn hóa (%) | 6,1 | 1,9 |
| CER chuẩn hóa (%) | 4,6 | 1,3 |
| Entity Accuracy (%) | 52,5 | 80,0 |
| Tiền đúng | 20/20 | 20/20 |
| SĐT đúng | 1/20 | 12/20 |

Medium raw WER/CER 11,7%/14,3%; WER chuẩn hóa macro clean/noisy 1,7%/2,4%. Timing sau ba warm-up: 17 effective samples, khoảng 45,99 giây/phút audio; model load 2,54 giây. Không so tốc độ với Small replay. Vẫn là TTS pending human listening, không có metric ngày hẹn/diarization, chưa có 12 audio BTC. Acceptance giữ UNDETERMINED, không coi WER thấp là PASS chính thức.

SĐT sai/thiếu: TEAM-EVAL-05, 06, 08, 14, 15, 16, 18, 19. Giữ transcript lỗi nguyên bản, không sửa chữ số để khớp GT và không tối ưu lại theo eval trong lượt này. Bộ từng được xem lỗi vẫn là regression, không tuyên bố test mù.

Lệnh đã chạy:

```bash
evaluation/asr/.venv/bin/python evaluation/asr/run_eval.py \
  --dataset evaluation/asr/datasets/synthetic-v1/eval \
  --model evaluation/asr/models/faster-whisper-medium \
  --expected-count 20 --profile baseline \
  --lock evaluation/asr/runs/dev-whisper-medium-v1/config.lock.json \
  --out evaluation/asr/runs/eval-whisper-medium-v1
```

Thư mục output đã tồn tại, không chạy lại vào cùng đường dẫn. Muốn lặp phép đo phải chọn thư mục mới và giữ lock.

## Trạng thái mới nhất — M1 trước, TTS ba miền chờ xử lý

FPT TTS vẫn là blocker: chưa gọi TTS có phí; chưa tải/chạy PhoWhisper. Dùng lại runner/scorer hiện có, không dựng runner mới.

- `datasets/catalog-v3/`: 4 script dev + 20 script eval, giá từ quote BTC, khách hàng giữa hai split tách biệt; có SĐT đa dạng và ngày hẹn. **Chưa có WAV**, GT vẫn pending. Hai giọng dự kiến không được coi là đã xác minh vùng miền.
- ITN v3 giữ chính xác `4.000.890 đồng`; ví dụ nói tắt trong đề vẫn được hỗ trợ. SĐT thiếu/thừa không tự sửa. Ngày hẹn ISO nằm trong `supplemental/<id>.json` và `supplemental_callback_accuracy`; không có GT ngày thì metric này là `null` (N/A).
- Ngày cụ thể hỗ trợ `DD/MM[/YYYY]` và `ngày … tháng … [năm …]`; ngày mai/ngày kia cần `call_date` công khai (hoặc `reference_date` của dataset). Thiếu năm dùng năm ngày gọi, không tự đẩy qua năm sau. Hai ngày khác nhau/invalid/không hiểu được → diagnostics, không đoán. Đây là thiết kế nhóm, chưa phải bộ hiểu thời gian tổng quát.
- `--expected-count` kiểm số dialogue đã khai báo. WAV thừa, thiếu hoặc hỏng làm coverage INCOMPLETE. `--warmup 3` loại ba audio đầu khỏi timing nhưng vẫn chấm toàn bộ chất lượng; bộ ít hơn hoặc bằng 3 audio có effective timing N/A. Replay không cung cấp thời gian nhận dạng.
- `runs/dev-v4-replay/` và `runs/eval-v4-replay/` chỉ chấm lại transcript cũ bằng code mới, **không phải benchmark model mới**. Kết quả chưa chứng minh cải thiện ASR; callback chưa có GT ở dataset cũ.

Chuẩn bị script offline, không gửi request TTS:

```bash
evaluation/asr/.venv/bin/python evaluation/asr/prepare_audio.py \
  --catalog-based --scripts-only --out evaluation/asr/datasets/catalog-v3
```

Sau khi có dịch vụ TTS dùng được, sinh audio vào cùng dataset bằng generator (chỉ khi script không đổi), nghe duyệt rồi khóa cấu hình dev trước eval. Nếu thay giọng/script phải tạo version mới. Script mới không được lấy đáp án từ model. Bộ cũ giữ làm regression; các số đo/lock v2 dưới đây là lịch sử, **không dùng lock cũ với code v3**.

[Mở trang nghe audio offline](datasets/synthetic-v1/listen.html). Mở HTML bằng trình duyệt; chọn **4 file dev** và bấm **Nghe riêng SĐT**. Trang có transcript dự kiến, ô xác nhận và nút xuất phiếu nghe duyệt JSON. Phiếu này không tự đổi GT thành đã duyệt.

## Những gì đang có

- Model đa ngôn ngữ Whisper Small lưu tại `models/faster-whisper-small/` (~464 MB), chạy CPU INT8 và không cần mạng khi nhận dạng.
- 4 audio `dev` để kiểm tra/tinh chỉnh kỹ thuật và 20 audio `eval` để đo sau khi khóa cấu hình.
- Hội thoại nhiều lượt về máy lọc không khí, hai giọng TTS, một phần có nhiễu trắng và giới hạn băng thông 300–3400 Hz.
- Scorer được import trực tiếp từ snapshot BTC, không viết lại công thức WER/CER/Entity Accuracy.

## Chạy

```bash
cd /Users/vqd/SUDO_PROJECT_MAIN
PYTHONPATH=evaluation/asr evaluation/asr/.venv/bin/python -m unittest evaluation/asr/test_asr.py

# Chỉ cần chạy lại nếu muốn tái tạo dữ liệu.
evaluation/asr/.venv/bin/python evaluation/asr/prepare_audio.py

# Dev trước. Chỉ chỉnh pipeline dựa vào dev.
evaluation/asr/.venv/bin/python evaluation/asr/run_eval.py \
  --dataset evaluation/asr/datasets/synthetic-v1/dev \
  --out evaluation/asr/runs/dev-next --profile baseline

# Khóa cấu hình rồi chạy đúng một lần trên 20 audio eval.
evaluation/asr/.venv/bin/python evaluation/asr/run_eval.py \
  --dataset evaluation/asr/datasets/synthetic-v1/eval \
  --out evaluation/asr/runs/eval-next --profile baseline \
  --lock evaluation/asr/runs/dev-next/config.lock.json
```

Mỗi lần chạy phải dùng thư mục `--out` mới; runner không ghi đè evidence cũ.

Đầu ra chính: `report.json`, `coverage.json`, `hypotheses.json`, `raw/btc_metrics.json`, `normalized/btc_metrics.json`, `errors.json`, `timing.json`, `manifest.json`, `config.lock.json`, transcript theo đoạn trong `segments/` và chẩn đoán trong `extraction/`.

`--lock` kiểm model/hash code/runtime/scorer/tham số với bản đã chạy trên dev. Các profile `vad`, `vad-prompt`, `phone-refine` là thử nghiệm; chưa được chọn làm mặc định vì không tốt hơn baseline trên dev. Mọi run hiện tại không cung cấp GT text, entity hoặc timing nhãn TTS cho ASR.

## Kết quả smoke test 03/10/2026

| Cohort | Coverage | Audio | WER chuẩn hóa | CER chuẩn hóa | Entity Accuracy | ASR giây/phút audio |
|---|---:|---:|---:|---:|---:|---:|
| Dev `runs/dev-r2` | 4/4 | 2,40 phút | 6,3% | 5,0% | 50,0% | 11,51 |
| Eval `runs/eval-r2` | 20/20 | 12,06 phút | 6,1% | 4,6% | 52,5% | 12,34 |

Eval gồm 15 file clean và 5 file nhiễu/băng thông mô phỏng; WER macro tương ứng là 4,7% và 10,1%. Có 40 entity GT, trong đó giá tiền nhận đúng và 19/20 số điện thoại nhận sai hoặc thiếu. Kết quả giữ `acceptance: UNDETERMINED` vì dữ liệu chưa được người nghe duyệt và BTC chưa công bố ngưỡng đạt.

## Tối ưu pipeline v3

Bản bàn giao mới: [report eval](runs/eval-v3-locked/report.json), [so sánh trước–sau](runs/comparison-v3/comparison.md), [lock từ dev](runs/dev-v3-locked/config.lock.json). Chạy đủ 20/20, điểm WER/CER/entity chưa tăng. Một lỗi cắt dãy SĐT 11 chữ số thành 10 chữ số đã được loại bỏ; dãy thiếu/thừa vẫn cần nghe duyệt.

Bản hiện tại kiểm WAV thiếu/hỏng/cắt cụt; schema hypothesis dùng lại contract; text rỗng và ID thiếu/thừa thành `INCOMPLETE`. Supplemental accuracy có mẫu số là toàn bộ GT cùng loại, kể cả hypothesis bị thiếu. Official metrics BTC vẫn giữ nguyên cách scorer tính và được đặt cạnh coverage.

ITN v2 hỗ trợ tiền nguyên VND viết bằng chữ/chữ số, giá 4.890.000 đồng và ngân sách. Giá/ngân sách cuối cùng có số rõ ràng được lấy làm slot dialogue; khoảng giá và số thập phân chưa hỗ trợ thì ghi chẩn đoán. SĐT phải là một dãy đúng 10 chữ số bắt đầu bằng 0; không cắt dãy dài hoặc tự thêm số thiếu. Date/SKU/area chưa được hỗ trợ và được báo rõ khi GT yêu cầu.

`primary_segments/` giữ bản ASR lần đầu. Profile thử nghiệm `phone-refine` có thêm `phone_retries/`, dùng vị trí đoạn SĐT từ ASR và tối đa một lần nhận lại; không dùng nhãn TTS để cắt đoạn. Thời gian retry nằm trong timing tổng.

Generator giữ GT hiện có (gồm trạng thái nghe duyệt), và từ chối tái sử dụng audio nếu script thay đổi. Muốn sửa script/audio, dùng một dataset version và `--out` mới.

## Ý nghĩa ground truth BTC

`asr/ground_truth.json` là đáp án chuẩn dùng **sau khi ASR chạy** để tính WER/CER và so entity. Nó không phải input cho model. BTC hiện chỉ công khai transcript của 4/12 hội thoại; audio của 12 hội thoại và 8 transcript còn lại được BTC giữ để chấm. Vì vậy pipeline này chưa thể tạo kết quả BTC chính thức.

## Ranh giới bằng chứng

Audio ở đây là fixture TTS của nhóm, không phải audio BTC hoặc giọng người thật. Transcript được sinh từ script và mang `review_status: pending_human_listening`; phải có người nghe, sửa và đổi sang `human_verified` trước khi dùng như golden set của nhóm. Bộ 20 audio đáp ứng số lượng bổ sung tối thiểu của nhánh ASR, nhưng chưa tự nó đáp ứng yêu cầu dữ liệu toàn dự án (ví dụ tổng audio/giờ, vùng miền và dữ liệu thật).

Không có ngưỡng đạt WER/CER chính thức trong tài liệu BTC đang nhận, nên report chỉ ghi số đo và `acceptance: UNDETERMINED`, không tự tuyên bố PASS.

## Khi BTC phát audio

Tạo thư mục mới có `ground_truth.json` nguyên bản và `audio/<Dxx>.wav`, rồi chạy cùng `run_eval.py`. Không trộn audio BTC vào bộ TTS và không sửa scorer. Nếu BTC dùng định dạng audio khác WAV PCM16 mono 16 kHz, chuyển thành một bản dẫn xuất và giữ hash file gốc trong manifest.
