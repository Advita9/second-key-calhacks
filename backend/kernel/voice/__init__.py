"""Voice is evidence, not identity. Nothing here identifies a speaker.

Text to speech renders Margaret's lines to cached WAV files. Speech to text turns a
player's push-to-talk clip into a transcript. A transcript is conversation evidence for
the extractor, exactly like typed text. No module in this package compares voices,
matches speakers, or asserts who is talking.

Providers are selected by env (`TTS_PROVIDER`, `STT_PROVIDER`: `mock` or `cartesia`).
Every provider fails closed: a TTS error yields no audio (the turn still answers with
`audio_url=None`), an STT error yields the transcript "[inaudible]" marked as mock.
"""

from __future__ import annotations

from kernel.voice.cache import AudioCache, audio_key, audio_url, default_cache_root
from kernel.voice.cartesia import CartesiaSTT, CartesiaTTS
from kernel.voice.factory import make_stt, make_tts, voice_mode
from kernel.voice.mock import MockSTT, MockTTS, silent_wav
from kernel.voice.types import INAUDIBLE, STT, TTS, Transcript

__all__ = [
    "INAUDIBLE",
    "STT",
    "TTS",
    "AudioCache",
    "CartesiaSTT",
    "CartesiaTTS",
    "MockSTT",
    "MockTTS",
    "Transcript",
    "audio_key",
    "audio_url",
    "default_cache_root",
    "make_stt",
    "make_tts",
    "silent_wav",
    "voice_mode",
]
