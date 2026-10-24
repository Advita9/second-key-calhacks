"""Disk cache for model responses: deterministic key, replay-only mode, hits skip the client."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import anthropic
import pytest

from kernel.llm.cache import ResponseCache
from kernel.llm.claude_extractor import ClaudeExtractor
from kernel.llm.types import ExtractorError
from tests.unit.test_claude_extractor import FakeClient, _response
from tests.unit.test_mock_extractor import load_case

MSGS: list[dict[str, Any]] = [{"role": "user", "content": "hello"}]
SCHEMA: dict[str, Any] = {"type": "object", "properties": {"a": {"type": "string"}}}


def test_same_request_same_key_and_any_change_differs() -> None:
    k = ResponseCache.key("m", "sys", MSGS, SCHEMA)
    assert k == ResponseCache.key("m", "sys", list(MSGS), dict(SCHEMA))
    assert len(k) == 64
    assert k != ResponseCache.key("m2", "sys", MSGS, SCHEMA)
    assert k != ResponseCache.key("m", "sys2", MSGS, SCHEMA)
    assert k != ResponseCache.key("m", "sys", [{"role": "user", "content": "hello!"}], SCHEMA)
    assert k != ResponseCache.key("m", "sys", MSGS, {**SCHEMA, "x": 1})
    # key order inside dicts does not matter (canonical json)
    assert k == ResponseCache.key(
        "m", "sys", MSGS, {"properties": SCHEMA["properties"], "type": "object"}
    )


def test_put_get_roundtrip_and_miss(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "llm", replay_only=False)
    k = ResponseCache.key("m", "sys", MSGS, SCHEMA)
    assert cache.get(k) is None
    cache.put(k, {"parsed": {"a": "b"}, "stop_reason": "end_turn"})
    assert cache.get(k) == {"parsed": {"a": "b"}, "stop_reason": "end_turn"}
    assert (tmp_path / "llm" / f"{k}.json").exists()


def test_corrupt_file_is_a_miss(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "llm", replay_only=False)
    k = ResponseCache.key("m", "sys", MSGS, SCHEMA)
    (tmp_path / "llm").mkdir()
    (tmp_path / "llm" / f"{k}.json").write_text("{not json")
    assert cache.get(k) is None


def test_replay_only_miss_raises_and_never_calls_client(tmp_path: Path) -> None:
    conv, p = load_case("S-03")
    client = FakeClient(_response(conv))
    ex = ClaudeExtractor(
        cast(anthropic.Anthropic, client),
        model="claude-test",
        cache=ResponseCache(tmp_path / "llm", replay_only=True),
    )
    with pytest.raises(ExtractorError):
        ex.extract(conv, p)
    assert client.messages.calls == []


def test_hit_never_calls_client(tmp_path: Path) -> None:
    conv, p = load_case("S-03")
    root = tmp_path / "llm"
    first = FakeClient(_response(conv))
    res1 = ClaudeExtractor(
        cast(anthropic.Anthropic, first),
        model="claude-test",
        cache=ResponseCache(root, replay_only=False),
    ).extract(conv, p)
    assert len(first.messages.calls) == 1

    second = FakeClient(error=AssertionError("client must not be called on a hit"))
    res2 = ClaudeExtractor(
        cast(anthropic.Anthropic, second),
        model="claude-test",
        cache=ResponseCache(root, replay_only=True),
    ).extract(conv, p)
    assert second.messages.calls == []
    assert res1 == res2


def test_cached_entry_is_revalidated(tmp_path: Path) -> None:
    """An edited cache file with a foreign id must fail closed, not slip through."""
    conv, p = load_case("S-03")
    root = tmp_path / "llm"
    client = FakeClient(_response(conv))
    ex = ClaudeExtractor(
        cast(anthropic.Anthropic, client),
        model="claude-test",
        cache=ResponseCache(root, replay_only=False),
    )
    ex.extract(conv, p)
    files = list(root.glob("*.json"))
    assert len(files) == 1
    files[0].write_text(
        '{"parsed": {"signals": [{"kind": "secrecy", "score": 0.9, "source_id": "EV-9999", '
        '"evidence_span": "x"}], "summary": ""}, "stop_reason": "end_turn"}'
    )
    with pytest.raises(ExtractorError):
        ex.extract(conv, p)
