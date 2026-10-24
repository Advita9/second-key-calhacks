from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import voice_routes
from kernel.voice.cache import audio_key
from kernel.voice.cartesia import CartesiaSTT


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AUDIO_CACHE_DIR", str(tmp_path / "audio"))
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    voice_routes.reset_providers()
    app = FastAPI()
    app.include_router(voice_routes.router)
    with TestClient(app) as c:
        yield c
    voice_routes.reset_providers()


def test_audio_404_for_unknown_or_bad_key(app: TestClient) -> None:
    assert app.get(f"/audio/{'0' * 64}.wav").status_code == 404
    assert app.get("/audio/not-a-key.wav").status_code == 404
    assert app.get("/audio/..%2F..%2Fetc%2Fpasswd.wav").status_code == 404


def test_audio_serves_cached_wav(app: TestClient, say_wav: bytes) -> None:
    key = audio_key("Hello, dear.", "v")
    voice_routes.get_cache().put(key, say_wav)
    r = app.get(f"/audio/{key}.wav")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.content == say_wav


def test_stt_mock_returns_hint_and_is_labeled_mock(app: TestClient, clip_webm: bytes) -> None:
    r = app.post(
        "/rooms/ROOM1/stt",
        files={"audio": ("clip.webm", clip_webm, "audio/webm")},
        data={"text": "send the money now"},
    )
    assert r.status_code == 200
    assert r.json() == {
        "transcript": "send the money now",
        "provider": "mock",
        "is_mock": True,
        "duration_s": None,
    }


def test_stt_mock_without_hint_is_inaudible(app: TestClient, clip_webm: bytes) -> None:
    r = app.post("/rooms/ROOM1/stt", files={"audio": ("clip.webm", clip_webm, "audio/webm")})
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "[inaudible]" and body["is_mock"] is True
    assert set(body) == {"transcript", "provider", "is_mock", "duration_s"}


def test_stt_rejects_empty_and_oversized(app: TestClient) -> None:
    assert (
        app.post("/rooms/R/stt", files={"audio": ("c.webm", b"", "audio/webm")}).status_code == 400
    )
    big = b"\x00" * (voice_routes.MAX_AUDIO_BYTES + 1)
    assert (
        app.post("/rooms/R/stt", files={"audio": ("c.webm", big, "audio/webm")}).status_code == 413
    )


def test_stt_real_provider_through_route(
    app: TestClient,
    clip_webm: bytes,
    stt_response: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=stt_response)

    real = CartesiaSTT("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    voice_routes.set_stt(real)
    r = app.post("/rooms/R/stt", files={"audio": ("clip.webm", clip_webm, "audio/webm")})
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == stt_response["text"]
    assert body["provider"] == "cartesia" and body["is_mock"] is False
    assert len(seen) == 1 and b"ink-whisper" in seen[0].content
    assert json.dumps(body)  # serializable
