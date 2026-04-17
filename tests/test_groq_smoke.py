"""Hallucination-regression guard for Groq two-call path.

Codifies the manual assertion from FEATURE_LIST_CLOUD_SPEED_V2.md: feeding
ambiguous speech through Groq must NOT produce a conversational reply.
Gated on GROQ_API_KEY and a user-recorded fixture at
`tests/fixtures/ambiguous_speech.wav` (16 kHz mono PCM_16, 2-3s).

Run with: `pytest tests/test_groq_smoke.py -v`
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ambiguous_speech.wav"

_HALLUCINATION_MARKERS = (
    "please go ahead",
    "start dictating",
    "i'll transcribe",
    "how can i help",
    "sure, please",
    "i'm ready to transcribe",
)


@pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set",
)
@pytest.mark.skipif(
    not _FIXTURE_PATH.exists(),
    reason=f"Fixture missing: {_FIXTURE_PATH} (record 2-3s of ambiguous speech)",
)
def test_groq_ambiguous_audio_does_not_return_chat_reply():
    import soundfile
    from groq_dictator import GroqDictator
    from postprocessor import build_cloud_system_prompt

    audio, sr = soundfile.read(_FIXTURE_PATH, dtype="float32")
    assert sr == 16000, f"fixture must be 16 kHz, got {sr}"
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # Collapse to mono if stereo.
    audio = np.asarray(audio, dtype=np.float32)

    dictator = GroqDictator(api_key=os.environ["GROQ_API_KEY"])
    prompt = build_cloud_system_prompt(
        vocabulary_text="",
        previous_segment="",
        mode="streaming",
    )

    result = dictator.dictate(audio, system_prompt=prompt)

    assert result, "Groq returned empty output for non-empty audio"
    lowered = result.lower()
    for marker in _HALLUCINATION_MARKERS:
        assert marker not in lowered, (
            f"chat-hallucination marker {marker!r} present in output: {result!r}"
        )
    assert len(result) < 200, (
        f"output suspiciously long for 2-3s input ({len(result)} chars): {result!r}"
    )
