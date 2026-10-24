from __future__ import annotations

import httpx

from kernel.voice.cache import AudioCache
from kernel.voice.cartesia import CartesiaSTT, CartesiaTTS
from kernel.voice.types import INAUDIBLE, Transcript


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_tts_http_error_returns_none_and_caches_nothing(cache: AudioCache) -> None:
    tts = CartesiaTTS("k", cache, client=_client(lambda _r: httpx.Response(429, text="slow down")))
    assert tts.synthesize("x", "v") is None
    assert cache.count() == 0


def test_tts_transport_exception_returns_none(cache: AudioCache) -> None:
    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    tts = CartesiaTTS("k", cache, client=_client(boom))
    assert tts.synthesize("x", "v") is None


def test_tts_non_wav_body_returns_none(cache: AudioCache) -> None:
    tts = CartesiaTTS("k", cache, client=_client(lambda _r: httpx.Response(200, json={"err": 1})))
    assert tts.synthesize("x", "v") is None
    assert cache.count() == 0


def test_turn_shape_on_tts_failure(cache: AudioCache) -> None:
    """What the turn handler does with None: audio_url is null, the text reply still goes out."""
    tts = CartesiaTTS("k", cache, client=_client(lambda _r: httpx.Response(500)))
    path = tts.synthesize("I do not give out numbers over the phone.", "v")
    reply = {"margaret_text": "I do not give out numbers over the phone.", "audio_url": None}
    if path is not None:
        reply["audio_url"] = f"/audio/{path.stem}.wav"
    assert reply["audio_url"] is None
    assert reply["margaret_text"]


def test_stt_http_error_is_inaudible_mock() -> None:
    stt = CartesiaSTT("k", client=_client(lambda _r: httpx.Response(500, text="nope")))
    t = stt.transcribe(b"abc", "audio/webm")
    assert t == Transcript(text=INAUDIBLE, provider="cartesia", is_mock=True, duration_s=None)


def test_stt_exception_is_inaudible_mock() -> None:
    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    t = CartesiaSTT("k", client=_client(boom)).transcribe(b"abc", "audio/webm")
    assert t.text == INAUDIBLE and t.is_mock is True


def test_stt_malformed_json_is_inaudible_mock() -> None:
    stt = CartesiaSTT("k", client=_client(lambda _r: httpx.Response(200, json={"type": "x"})))
    t = stt.transcribe(b"abc", "audio/webm")
    assert t.text == INAUDIBLE and t.is_mock is True


def test_stt_empty_text_is_inaudible_but_real() -> None:
    stt = CartesiaSTT("k", client=_client(lambda _r: httpx.Response(200, json={"text": "  "})))
    t = stt.transcribe(b"abc", "audio/webm")
    assert t.text == INAUDIBLE and t.is_mock is False
