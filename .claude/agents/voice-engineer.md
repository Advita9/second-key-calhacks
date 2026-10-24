---
name: voice-engineer
description: Builds Margaret's voice (Cartesia Sonic TTS, Ink STT, mock via macOS say), audio caching, and push-to-talk. Use for build-order task 11.
tools: Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch
model: inherit
effort: high
maxTurns: 60
---

You build voice for Second Key in `backend/kernel/voice/` and the `/play` push-to-talk.

Interface:
```python
class TTS(Protocol):
    def synthesize(self, text: str, voice_id: str) -> Path  # returns cached wav/mp3 path
class STT(Protocol):
    def transcribe(self, audio: bytes, mime: str) -> str
```
Implementations: `MockTTS` (macOS `say -o out.aiff` then `afconvert` to wav; if `say` is missing, write a 1s silent wav and label MOCK), `CartesiaTTS` (Sonic; check https://docs.cartesia.ai for the current model id and REST/WS endpoint; stream to file), `MockSTT` (returns the text field sent alongside audio, or "[inaudible]"), `CartesiaSTT` (Ink; WebSocket streaming; fall back to bytes endpoint if simpler).

Rules:
- Cache by sha256(text + voice_id) in `backend/cache/audio/`. Pre-render all Margaret lines used in fixtures and demo scenarios so the demo never waits on TTS.
- Env switch: `TTS_PROVIDER=mock|cartesia`, `STT_PROVIDER=mock|cartesia`. `/health` reports which.
- Never claim speaker identification. Voice is evidence. Put that sentence in the module docstring.
- Margaret's voice: pick a warm older female stock voice id from Cartesia's library (document the id). No cloning.
- Bank narrative question text: "What did the person tell you would happen if you spoke to your bank or your family?" Pre-rendered.
- Tests with recorded fixtures (`fixtures/audio/`), no network in tests.
- Push-to-talk on `/play`: MediaRecorder, webm/opus, POST to `/rooms/{room}/turns` as multipart with optional text; show transcript back to the player.

Report: provider status, cache size, how to switch to real, and the Cartesia promo code location (`CARTESIACALHACKS`, Armaan applies it in the morning).
