# Demo mode

`DEMO_MODE=1` enables the two demo-only routes (`POST /payments/{id}/mutate`, `POST /audit/tamper`). It no longer decides whether the Claude extractor and Claude Margaret may call the network; that is `LLM_CACHE_MODE`:

- `auto` (default): disk cache first, network on a miss when `ANTHROPIC_API_KEY` is set, and the answer is written to the cache.
- `replay`: cache only. A miss never touches the network: the extractor fails closed (HOLD, rule `X-00`) and Margaret answers the safe line.
- `live`: skip cache reads (every lookup is a miss) but keep writing, for re-recording after a prompt change.

`LLM_CACHE_WARM=1` is kept as an alias for `auto`. `GET /health` reports the mode as `mode.llm_cache`. Every model call is keyed by sha256 of the full request (model, system prompt, messages, output schema) and stored in `backend/cache/llm/<key>.json`. Without a key, or with `MOCK_EXTRACTOR=1` / `MOCK_MARGARET=1`, the mocks run instead and no cache is involved.

`scripts/demo.py --real` run with `DEMO_MODE=1` in the environment and without `--warm` sets `LLM_CACHE_MODE=replay` itself, so the offline guarantee on stage does not depend on `.env`. It also sends `X-Ops-Token` (from `OPS_TOKEN`) on every request. Decisions (outcome, rule ids, signals, policy version) and the transcript of every payment are persisted in SQLite next to the payment, so the holds queue keeps its rule ids across a restart and `mutate` after a restart re-runs the extractor on the stored transcript; it only fails closed (`X-00`) when the transcript is truly absent.

Warm the cache once with the real key (a handful of calls): `uv run --project backend python scripts/demo.py --warm`. It runs the whole demo with `LLM_CACHE_WARM=1` (misses fill the cache) and then pushes S-03, L-01 and L-40 through the extractor. Margaret's history grows every turn, so each turn of the scenario A script is its own cache entry; the warm run covers all of them. Re-run `--warm` after changing a prompt, the persona, the script in `scripts/demo.py`, or `ANTHROPIC_MODEL`.

Replayed on stage: scenario A's Margaret turns and the extractor runs for the room payment, L-01 (scenario B), L-40 (scenario C) and S-03. Mocked in the demo regardless of keys: TTS and STT (`TTS_PROVIDER=mock`, cached WAV under `backend/cache/audio/`), the Nessie rail (`NESSIE_API_KEY=""`), and the room store (`ROOM_BACKEND=memory`). `GET /health` reports every mode and `cache: {llm_entries, audio_entries}`.

Commands: offline mock demo (acceptance G7): `cd backend && DEMO_MODE=1 uv run python ../scripts/demo.py`. Replay with the real key and zero network calls: `cd backend && DEMO_MODE=1 uv run python ../scripts/demo.py --real` (the scoreboard's `llm cache` line must show `misses=0`). Real with write-through: `uv run --project backend python scripts/demo.py --real`. Add `--json` to get the scoreboard as JSON on the last line.
