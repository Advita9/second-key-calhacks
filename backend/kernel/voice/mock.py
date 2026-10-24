"""MOCK voice providers. Output is labeled MOCK wherever a user can see it.

MockTTS: macOS `say -o out.aiff`, then `afconvert` to 16-bit 24 kHz WAV. If either tool
is missing, writes a 1 second silent WAV so the demo still plays something.
MockSTT: returns the text typed alongside the clip (`hint`) or "[inaudible]".
Neither identifies a speaker.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from kernel.voice.cache import AudioCache, audio_key
from kernel.voice.types import INAUDIBLE, Transcript

log = logging.getLogger("second_key.voice")

MOCK_VOICE_PREFIX = "mock:"


def silent_wav(seconds: float = 1.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


class MockTTS:
    name = "mock"
    is_mock = True

    def __init__(
        self,
        cache: AudioCache,
        say_bin: str = "/usr/bin/say",
        afconvert_bin: str = "/usr/bin/afconvert",
        sample_rate: int = 24000,
        timeout_s: float = 30.0,
    ) -> None:
        self.cache = cache
        self.say_bin = say_bin
        self.afconvert_bin = afconvert_bin
        self.sample_rate = sample_rate
        self.timeout_s = timeout_s

    @property
    def tools_available(self) -> bool:
        return bool(shutil.which(self.say_bin) and shutil.which(self.afconvert_bin))

    def cache_key(self, text: str, voice_id: str) -> str:
        # Namespaced so a `say` render never collides with a Cartesia render of the same line.
        return audio_key(text, MOCK_VOICE_PREFIX + voice_id)

    def synthesize(self, text: str, voice_id: str) -> Path | None:
        key = self.cache_key(text, voice_id)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        try:
            wav = self._render(text) if self.tools_available else self._silent()
        except Exception:
            log.exception("MockTTS render failed; using silent wav")
            wav = self._silent()
        try:
            return self.cache.put(key, wav)
        except Exception:
            log.exception("MockTTS cache write failed")
            return None

    def _silent(self) -> bytes:
        log.warning("MockTTS: say/afconvert unavailable, writing 1s silent wav (MOCK)")
        return silent_wav(1.0, self.sample_rate)

    def _render(self, text: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="sk-say-") as d:
            tmp = Path(d)
            txt = tmp / "line.txt"
            aiff = tmp / "out.aiff"
            out = tmp / "out.wav"
            txt.write_text(text, encoding="utf-8")
            subprocess.run(
                [self.say_bin, "-o", str(aiff), "-f", str(txt)],
                check=True,
                capture_output=True,
                timeout=self.timeout_s,
            )
            subprocess.run(
                [
                    self.afconvert_bin,
                    "-f",
                    "WAVE",
                    "-d",
                    f"LEI16@{self.sample_rate}",
                    str(aiff),
                    str(out),
                ],
                check=True,
                capture_output=True,
                timeout=self.timeout_s,
            )
            data = out.read_bytes()
        if not data.startswith(b"RIFF"):
            raise RuntimeError("afconvert did not produce a RIFF/WAVE file")
        return data


class MockSTT:
    name = "mock"
    is_mock = True

    def transcribe(self, audio: bytes, mime: str, *, hint: str | None = None) -> Transcript:
        text = hint.strip() if hint and hint.strip() else INAUDIBLE
        return Transcript(text=text, provider=self.name, is_mock=True, duration_s=None)
