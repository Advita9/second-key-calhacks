from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "prerender_audio.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prerender_audio", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_collects_narrative_question_fallbacks_and_case_lines() -> None:
    mod = _load()
    lines = mod.collect_lines()
    assert lines[0] == (
        "What did the person tell you would happen if you spoke to your bank or your family?"
    )
    assert (
        "I do not give out any numbers over the phone. The bank was very clear about that." in lines
    )
    assert any("Bay Roofing" in t or "pantry" in t for t in lines)
    assert len(lines) == len(set(lines))
    assert len(lines) >= 13
    for t in lines:
        assert "\u2014" not in t, "no em dashes in Margaret lines"


def test_prerender_is_idempotent_with_silent_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AUDIO_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("TTS_PROVIDER", "mock")
    monkeypatch.setattr(shutil, "which", lambda _c: None)  # silent fallback: fast, no `say`
    mod = _load()
    assert mod.main([]) == 0
    first = capsys.readouterr().out
    n = len(list(tmp_path.glob("*.wav")))
    assert n == len(mod.collect_lines())
    assert f"rendered={n} cached=0" in first
    assert mod.main([]) == 0
    second = capsys.readouterr().out
    assert f"rendered=0 cached={n}" in second
    assert "provider=mock" in second
