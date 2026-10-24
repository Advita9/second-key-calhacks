"""G7: `scripts/demo.py` runs offline in mock mode and prints the expected scoreboard."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

import pytest

from api import deps

DEMO_PATH = Path(__file__).resolve().parents[3] / "scripts" / "demo.py"


def load_demo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("second_key_demo", DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def demo(env: dict[str, str]) -> ModuleType:
    """`env` pins mocks, an in-memory DB and temp cache dirs; the demo keeps those."""
    return load_demo()


def test_mock_demo_scoreboard(demo: ModuleType) -> None:
    out = io.StringIO()
    board = demo.run(out=out)
    text = out.getvalue()
    assert board["ok"] is True, text
    assert board["unauthorized_releases"] == 0
    assert board["legit_completed"] == 1
    assert board["attacks_refused"] == 4 and board["attacks_total"] == 4
    assert board["audit_tamper_detected"] is True
    assert board["failures"] == []
    assert board["modes"]["extractor"] == "mock" and board["modes"]["margaret"] == "mock"
    # Replay-only with mocks: the disk cache is never consulted, so no misses either.
    assert board["llm_cache"]["misses"] == 0 and board["llm_cache"]["replay_only"] is True
    assert board["total_seconds"] < 30
    # One line per step, the attack refusals and the scoreboard are all printed.
    for marker in ("[1] ok", "[2] ok", "[3] ok", "[4] ok", "[5] ok", "[6] ok", "SCOREBOARD"):
        assert marker in text, marker
    # Each attack line carries the kernel's own text plus the expected invariant; the
    # self-approve attack's own text is ATTESTATION REFUSED, never a second prefix.
    for inv in ("POLICY_HOLD", "I2_FINGERPRINT", "I3_REPLAY", "I5_CONFLICT"):
        assert inv in text
    for kernel_text in (
        "SETTLEMENT REFUSED · I2_FINGERPRINT",
        "SETTLEMENT REFUSED · I3_REPLAY",
        "ATTESTATION REFUSED · I5_CONFLICT",
    ):
        assert kernel_text in text
    attack_line = next(line for line in text.splitlines() if "/attack/self-approve" in line)
    assert "ATTESTATION REFUSED" in attack_line and "SETTLEMENT REFUSED" not in attack_line
    assert "unauthorized releases : 0" in text and "result                : PASS" in text
    assert set(board["health_cache"]) == {"llm_entries", "audio_entries"}


def test_demo_json_flag_prints_scoreboard_last(demo: ModuleType) -> None:
    import json

    out = io.StringIO()
    board = demo.run(json_out=True, out=out)
    last = out.getvalue().rstrip("\n").splitlines()[-1]
    assert json.loads(last) == json.loads(json.dumps(board, sort_keys=True))


def test_demo_restores_environment_and_singletons(
    demo: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.delenv("LLM_CACHE_WARM", raising=False)
    monkeypatch.setenv("DEMO_MODE", "0")
    demo.run(out=io.StringIO())
    assert os.environ.get("DEMO_MODE") == "0"
    assert "LLM_CACHE_WARM" not in os.environ
    deps.reset()
