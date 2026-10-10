# Evaluation — code đang dùng

Đọc [CODE-HANDOFF.md](CODE-HANDOFF.md) trước khi sửa code. Kiến trúc sản phẩm hiện hành ở [docs/design.md](../docs/design.md); agent, hot/cold pipeline và MCP đang ở `../backend/src/`. Folder này chứa evaluator/contract/dataset, **không chứa một bản product architecture thứ hai**.

Điểm vào: `run_eval.py` → `eval_harness/__main__.py`. Code chấm ở `eval_harness/`; [đề bài](requirements/project-brief.pdf) và contract/nguồn BTC pin ở `evaluation-contracts/`; dữ liệu JSON 5 scenario ở `datasets/output1-btc-diagnostic-v1/` và nguồn `output (1)/`. Không sửa nguồn/GT đã pin; tạo revision mới.

Bộ source-only này không kèm unit tests, run lịch sử, ASR audio/model hay virtualenv theo yêu cầu bàn giao.

## Running the team's agent

One command, from the repository root:

```sh
backend/.venv/bin/python evaluation/run_eval.py evaluate
```

`evaluate` (in `product.py`) pins the inputs, runs the agent through `run_fixed` with `product_adapter.py` (which starts `../backend/src/pipeline/eval/bridge.py`; business tools come back to this harness's mock), collects with `extractor-prompt.txt` through `../backend/src/pipeline/eval/extract_command.py`, and scores with the organisers' grader and this harness's checks.

Output: `runs/<date-time>/` (or `--out`), with `inputs/`, `raw/`, `evidence/` and `scored/`; the table is `scored/scorer.stdout.txt`, the summary `execution-report.json`. The root README, Getting started section 5, says what each folder holds. P6 (`report`) is not run: it implements level M1 and these scenarios are M2.
