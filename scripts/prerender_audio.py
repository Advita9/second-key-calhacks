#!/usr/bin/env python3
"""Pre-render every Margaret line into backend/cache/audio so the demo never waits on TTS.

Sources:
  fixtures/margaret.md          "MockMargaret fallback replies" numbered lines
  fixtures/cases/*.json         every conversation item with speaker "margaret"
  the bank narrative question   "What did the person tell you would happen if you spoke to
                                 your bank or your family?"

Idempotent: cache hits are skipped. Provider follows TTS_PROVIDER (mock|cartesia) and the
voice follows CARTESIA_VOICE_ID. Run from the repo root:

  uv run --project backend python scripts/prerender_audio.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from kernel.voice.cache import AudioCache, default_cache_root  # noqa: E402
from kernel.voice.factory import make_tts, voice_id, voice_mode  # noqa: E402

BANK_NARRATIVE_QUESTION = (
    "What did the person tell you would happen if you spoke to your bank or your family?"
)

_FALLBACK_HEADER = "## MockMargaret fallback replies"
_NUMBERED_QUOTE = re.compile(r'^\s*\d+\.\s+"(.+)"\s*$')


def margaret_fallback_lines(md: Path) -> list[str]:
    lines: list[str] = []
    in_section = False
    for raw in md.read_text(encoding="utf-8").splitlines():
        if raw.startswith("## "):
            in_section = raw.strip() == _FALLBACK_HEADER
            continue
        if not in_section:
            continue
        m = _NUMBERED_QUOTE.match(raw)
        if m:
            lines.append(m.group(1))
    return lines


def margaret_case_lines(cases_dir: Path) -> list[str]:
    lines: list[str] = []
    for f in sorted(cases_dir.glob("*.json")):
        case = json.loads(f.read_text(encoding="utf-8"))
        for item in case.get("conversation", []):
            if item.get("speaker") == "margaret" and item.get("text"):
                lines.append(str(item["text"]))
    return lines


def collect_lines() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for text in [
        BANK_NARRATIVE_QUESTION,
        *margaret_fallback_lines(ROOT / "fixtures" / "margaret.md"),
        *margaret_case_lines(ROOT / "fixtures" / "cases"),
    ]:
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list lines, render nothing")
    args = ap.parse_args(argv)

    lines = collect_lines()
    mode = voice_mode()["tts"]
    cache = AudioCache(default_cache_root())
    tts = make_tts(os.environ, cache)
    vid = voice_id()
    print(f"provider={tts.name} mode={mode} voice_id={vid} lines={len(lines)} cache={cache.root}")
    if args.dry_run:
        for t in lines:
            print(f"  {t}")
        return 0

    rendered = 0
    hits = 0
    failed = 0
    t0 = time.perf_counter()
    for text in lines:
        if cache.get(tts.cache_key(text, vid)) is not None:
            hits += 1
            continue
        path = tts.synthesize(text, vid)
        if path is None:
            failed += 1
            print(f"  FAILED: {text[:60]}")
        else:
            rendered += 1
    elapsed = time.perf_counter() - t0
    print(
        f"rendered={rendered} cached={hits} failed={failed} "
        f"elapsed={elapsed:.1f}s cache_files={cache.count()} "
        f"cache_bytes={cache.size_bytes()}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
