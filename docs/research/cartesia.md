# Cartesia API research (researcher agent, 2026-10-23 22:25)

Many docs.cartesia.ai guide pages redirect to a login wall; findings below come from public API reference pages, the SDK source on GitHub, PyPI, and cartesia.ai public pages. UNVERIFIED items are marked.

## TTS REST (Sonic)
- `POST https://api.cartesia.ai/tts/bytes`, JSON body `{model_id, transcript, voice: {id}, output_format}`, returns raw audio bytes.
- Current model id: `sonic-3.6` (default) or `sonic-latest`; `sonic-3.5`, `sonic-3` accepted. `sonic-2` / `sonic-turbo` are NOT in the current enum. Do not use them.
- Header `Cartesia-Version: 2026-08-14` (only value the current spec allows).
- Auth: REST uses `Authorization: Bearer sk_car_...` (SDK does this). WebSocket uses `X-API-Key` header or `access_token` query param.
- WAV: `output_format = {"container":"wav","encoding":"pcm_s16le","sample_rate":44100}` returns a playable WAV. Sample rates: 8000, 16000, 22050, 24000, 44100, 48000. MP3: `{"container":"mp3","sample_rate":44100,"bit_rate":128000}`.
- `voice`: string id or `{"id": ...}`. Optional `language: "en"`, `generation_config: {speed 0.6..1.5, volume 0.5..2.0, emotion}` on sonic-3+. Never set both `language` and `locale`.
- Source: https://docs.cartesia.ai/api-reference/tts/bytes, https://docs.cartesia.ai/build-with-cartesia/models/tts

## Voice candidates (stock, feminine, warm; age UNVERIFIED)
- Ailsa (British, "Warm Guide") `fb02b554-7d64-4f90-841e-e57fc88f410c`
- Siobhan (Irish, "Warm Welcomer") `d79d2b77-9192-4e10-9407-5d43ca034803`
- Charlotte (British, "Heiress") `71a7ad14-091c-4e8e-a314-022ece01c121`
- Docs example: Skylar ("Friendly Guide", en) `db6b0ed5-d5d3-463d-ae85-518a07d3c2b4`
- Safest: `GET https://api.cartesia.ai/voices?gender=feminine&limit=100` and filter description for mature/older/grandmother at setup time; record the chosen id in `.env` as `CARTESIA_VOICE_ID`.
- Source: https://www.cartesia.ai/voices/female-voice, https://docs.cartesia.ai/api-reference/voices/list

## STT (Ink)
- Batch REST: `POST https://api.cartesia.ai/stt`, multipart `file` + `model=ink-whisper` (only model in the batch enum), optional `language` (default en), `timestamp_granularities[]=word`. Response JSON `{type: "transcript", text, language, duration, words?}`. Accepts flac, m4a, mp3, mp4, mpeg, mpga, oga, ogg, wav, webm. Any length.
- WebSocket: `wss://api.cartesia.ai/stt/websocket?model=ink-2&encoding=pcm_s16le&sample_rate=16000&cartesia_version=2026-08-14`, raw PCM only, send text `finalize` to flush. Models `ink-2, ink-preview, ink-whisper`.
- For browser push-to-talk webm/opus blobs: use batch REST (`ink-whisper`). WebSocket would need PCM decoding first.
- Source: https://docs.cartesia.ai/api-reference/stt/transcribe, https://docs.cartesia.ai/api-reference/stt/stt

## Python SDK
- PyPI `cartesia` 4.2.0 (Sep 2026), Stainless-generated. `Cartesia(api_key=...)` (does NOT read env itself; pass api_key explicitly). Default header `cartesia-version: 2026-08-14`.
- TTS: `client.tts.generate(model_id=..., output_format={...}, transcript=..., voice="<id>") -> BinaryAPIResponse`; `.write_to_file(path)` confirmed; `.read()` for bytes (Stainless convention, UNVERIFIED here).
- STT: `client.stt.transcribe(file=Path("clip.webm"), model="ink-whisper", language="en") -> STTTranscribeResponse`; `.text` (field name per API; UNVERIFIED on SDK object).
- `client.tts.bytes(...)` does NOT exist in 4.x (old tutorials).
- Decision: our client may use plain `httpx` against the two REST endpoints instead of the SDK to keep deps small; both are documented above.

## Limits / promo
- Free: 20K credits/month, concurrency 2 TTS / 8 STT. Pro $5/mo: 100K credits, 3 TTS / 12 STT. Serialize TTS calls (free tier concurrency 2) or expect 429s in a live room.
- `CARTESIACALHACKS` promo: redemption mechanism not found in public docs. Armaan applies it in play.cartesia.ai billing in the morning. Do not design around the credits.

## Lead probe 2026-10-23 22:38 (live, read-only GET /voices with our key)
- Auth `Authorization: Bearer` + `Cartesia-Version: 2026-08-14` returned 200 with 100 feminine voices. Fields: id, name, description, tagline, language, gender, country, accents, is_pro.
- Chosen default stock voice: **Michelle** `d7bf7d75-64b7-4c1e-86c0-79d647366587` ("Gentle and reassuring tone designed to offer comfort and build trust", en). Alternatives: Sheryl `cfce9402-0067-458b-95a7-95846f469406` (warm, understanding), Julia `273f9ef7-9fc2-4def-88bb-ab108c6249ca` (soft, composed). Set via `CARTESIA_VOICE_ID`. No voice cloning anywhere.
