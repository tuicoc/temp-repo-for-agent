# Voice lab

The bench where the voice channel was designed. The product's voice path
(`src/components/voice`, `src/api/voice.py`) grew out of it; this stays as
the place to try recognisers, endpointing and voices before they reach it.
Talk to the agent in the browser, hear it answer, and see how long each
stage took. Everything except the agent runs on this machine, on CPU.

```
mic -> resample to 16 kHz -> Silero VAD + Smart Turn -> local ASR -> lexicon
    -> the backend's turn endpoint (or echo) -> VieNeu TTS, streamed -> speaker
```

## Run

Python 3.12. On an Intel Mac `onnxruntime` must stay at 1.23.2, the last
release with x86_64 wheels, and `numba`/`llvmlite` are pinned for the same
reason.

```
cd backend/lab/voice
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python fetch_models.py
.venv/bin/python -m uvicorn server:app --port 8100
```

Open http://127.0.0.1:8100 in Chrome. The first use of VieNeu downloads its
model, which takes minutes; later sessions load it in about 15 s.

For the real agent, the backend must be running on port 8000 with Postgres
up (see the main README); the lab signs in with `SEED_CUSTOMER_EMAIL` and
`SEED_CUSTOMER_PASSWORD` from `backend/.env`. Pick "Echo" to test the voice
path without spending model quota.

## Files

| File | Part |
|---|---|
| `server.py` | WebSocket session: audio in, events and audio out, timing |
| `turns.py` | Silero VAD, Smart Turn v3.2, end of turn, barge-in |
| `asr.py` | Local recognisers behind one call |
| `lexicon.py`, `lexicon.json` | Hotwords and corrections for misheard words |
| `tts.py` | VieNeu (local, streaming) and Edge voices |
| `bridge.py` | The backend's turn endpoint, or echo |
| `bench.py` | WER, CER and speed of every recogniser on a folder of clips |
| `static/` | The page |

## Bench the recognisers offline

```
.venv/bin/python bench.py samples
.venv/bin/python bench.py run --show
```

`samples` synthesises eight test sentences; `run --dir PATH` scores any folder
of `<name>.wav` with a `<name>.txt` reference. Timings per turn from the page
are appended to `runs/<date>.jsonl`.
