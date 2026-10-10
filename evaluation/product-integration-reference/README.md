# Evaluation-specific product integration reference

**LEGACY — KHÔNG PHẢI SOURCE ĐANG CHẠY.** Agent/MCP/graph hiện hành nằm trong `../../backend/src/`; đọc `../CODE-HANDOFF.md` trước. Folder này chỉ giữ bridge cũ để truy vết và so sánh, không copy đè lên product.

These files are the **last local integration state before product was restored to a clean `origin/main` checkout on 10/10/2026**. They are reference copies under `evaluation/`, not active backend/frontend code. `FILES.txt` lists every copied path relative to the product repository. Unit tests were omitted for this source-only handoff. No `.env`, database, virtualenv, downloaded model, or production credential is included.

The old integration was developed against product commit `5a1c8ee`; the clean `dai` base is `be8e85e`. Compare each reference file with the current product file and port only relevant changes on a new commit. Never copy the whole folder over `backend/` or `frontend/`: `main` changed in between. Run targeted tests after porting. The reference contains both new modules and modified existing files so the bridge can be reconstructed without the original local archive.

Known limits at capture time: FastMCP business/memory boundaries were in-process, not isolated servers; memory writer MCP and LangGraph checkpointer were not implemented. Product PostgreSQL tests had passed before the final memory MCP change, but were not rerun successfully after it. These files are not M1/M2 acceptance evidence.
