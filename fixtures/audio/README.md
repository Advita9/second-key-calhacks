# Recorded voice fixtures (no network in tests)

- `say_sample.wav`: 24 kHz 16-bit mono WAV rendered by macOS `say` + `afconvert` for "Hello, dear." Used as the fake TTS response body in tests.
- `clip.webm`: webm/opus clip (ffmpeg from a `say` render of the bank narrative question). Shape matches a browser MediaRecorder blob. STT input in tests.
- `stt_response.json`: RECORDED body of one live Cartesia `POST /stt` (ink-whisper) call on 2026-10-23 with `clip.webm`. Transcript matched the clip verbatim, 109 ms.
- `tts_bytes.wav` + `tts_recorded.json`: RECORDED body and request metadata of one live Cartesia `POST /tts/bytes` call (sonic-3.6, stock voice Michelle `d7bf7d75-64b7-4c1e-86c0-79d647366587`) on 2026-10-23, 738 ms. The API key is redacted in the metadata.

Voice is evidence, not identity. Nothing in these fixtures identifies a speaker.
