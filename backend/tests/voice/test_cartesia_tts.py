from __future__ import annotations

import json
import threading
import time

import httpx

from kernel.voice.cache import AudioCache, audio_key
from kernel.voice.cartesia import CartesiaTTS

VOICE = "d7bf7d75-64b7-4c1e-86c0-79d647366587"


def test_sends_exact_request_and_caches_bytes(cache: AudioCache, say_wav: bytes) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=say_wav, headers={"content-type": "audio/wav"})

    tts = CartesiaTTS(
        "sk_car_test", cache, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    p = tts.synthesize("Hello, dear.", VOICE)
    assert p is not None and p.read_bytes() == say_wav
    assert p == cache.root / f"{audio_key('Hello, dear.', VOICE)}.wav"

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "https://api.cartesia.ai/tts/bytes"
    assert req.headers["Authorization"] == "Bearer sk_car_test"
    assert req.headers["Cartesia-Version"] == "2026-08-14"
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == {
        "model_id": "sonic-3.6",
        "transcript": "Hello, dear.",
        "voice": {"id": VOICE},
        "language": "en",
        "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000},
    }


def test_second_call_same_text_does_not_hit_transport(cache: AudioCache, say_wav: bytes) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=say_wav)

    tts = CartesiaTTS("k", cache, client=httpx.Client(transport=httpx.MockTransport(handler)))
    a = tts.synthesize("Same line.", VOICE)
    b = tts.synthesize("Same line.", VOICE)
    assert a == b and calls == 1
    tts.synthesize("Same line.", "other-voice")
    assert calls == 2


def test_default_voice_used_when_blank(cache: AudioCache, say_wav: bytes) -> None:
    bodies: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, content=say_wav)

    tts = CartesiaTTS(
        "k", cache, voice_default=VOICE, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    p = tts.synthesize("x", "")
    assert p is not None and p.stem == audio_key("x", VOICE)
    assert bodies[0]["voice"] == {"id": VOICE}


def test_calls_are_serialized_by_lock(cache: AudioCache, say_wav: bytes) -> None:
    active = 0
    peak = 0
    guard = threading.Lock()

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with guard:
            active -= 1
        return httpx.Response(200, content=say_wav)

    tts = CartesiaTTS("k", cache, client=httpx.Client(transport=httpx.MockTransport(handler)))
    threads = [threading.Thread(target=tts.synthesize, args=(f"line {i}", VOICE)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1
    assert cache.count() == 6
