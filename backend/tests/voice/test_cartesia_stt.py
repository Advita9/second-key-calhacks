from __future__ import annotations

import httpx

from kernel.voice.cartesia import CartesiaSTT
from kernel.voice.types import Transcript


def test_sends_multipart_ink_whisper_and_returns_recorded_text(
    clip_webm: bytes, stt_response: dict[str, object]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=stt_response)

    stt = CartesiaSTT("sk_car_test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    t = stt.transcribe(clip_webm, "audio/webm;codecs=opus")

    assert isinstance(t, Transcript)
    assert t.text == stt_response["text"]
    assert t.provider == "cartesia" and t.is_mock is False
    assert t.duration_s == float(str(stt_response["duration"]))

    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "https://api.cartesia.ai/stt"
    assert req.headers["Authorization"] == "Bearer sk_car_test"
    assert req.headers["Cartesia-Version"] == "2026-08-14"
    ctype = req.headers["content-type"]
    assert ctype.startswith("multipart/form-data; boundary=")
    body = req.content
    assert b'name="model"\r\n\r\nink-whisper\r\n' in body
    assert b'name="language"\r\n\r\nen\r\n' in body
    assert b'name="file"; filename="clip.webm"' in body
    assert b"Content-Type: audio/webm;codecs=opus" in body
    assert clip_webm in body


def test_hint_is_ignored_by_real_provider(stt_response: dict[str, object]) -> None:
    stt = CartesiaSTT(
        "k",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=stt_response))
        ),
    )
    t = stt.transcribe(b"\x1aE\xdf\xa3", "audio/webm", hint="typed text")
    assert t.text == stt_response["text"]
