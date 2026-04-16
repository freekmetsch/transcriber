"""Audio feedback tones for recording state transitions.

Tones are generated as sine waves at import time and stored in memory.
Playback is async (non-blocking) via winsound.
"""

import io
import logging
import math
import struct
import wave
import winsound

log = logging.getLogger("transcriber.sounds")


def _generate_tone(frequency: float, duration_ms: int, volume: float = 0.3,
                   sample_rate: int = 16000, fade_ms: int = 5) -> bytes:
    """Generate a sine wave tone as WAV bytes in memory."""
    n_samples = int(sample_rate * duration_ms / 1000)
    fade_samples = int(sample_rate * fade_ms / 1000)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            sample = math.sin(2 * math.pi * frequency * i / sample_rate)
            sample *= volume
            if i < fade_samples:
                sample *= i / fade_samples
            elif i > n_samples - fade_samples:
                sample *= (n_samples - i) / fade_samples
            wf.writeframes(struct.pack("<h", int(sample * 32767)))
    return buf.getvalue()


def _generate_two_tone(freq1: float, freq2: float,
                       duration_ms: int = 80, **kwargs) -> bytes:
    """Generate two consecutive tones as a single WAV."""
    sample_rate = kwargs.get("sample_rate", 16000)
    n_per_tone = int(sample_rate * duration_ms / 1000)
    fade_ms = kwargs.get("fade_ms", 5)
    fade_samples = int(sample_rate * fade_ms / 1000)
    volume = kwargs.get("volume", 0.3)

    frames = bytearray()
    for freq in (freq1, freq2):
        for i in range(n_per_tone):
            sample = math.sin(2 * math.pi * freq * i / sample_rate)
            sample *= volume
            if i < fade_samples:
                sample *= i / fade_samples
            elif i > n_per_tone - fade_samples:
                sample *= (n_per_tone - i) / fade_samples
            frames.extend(struct.pack("<h", int(sample * 32767)))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


# Pre-generate tones at import time
_SOUND_START = _generate_two_tone(880, 1100)      # Ascending — recording on
_SOUND_STOP = _generate_two_tone(1100, 880)       # Descending — recording off
_SOUND_ERROR = _generate_tone(330, 200, volume=0.2)  # Low buzz — error

_enabled = True


def set_enabled(enabled: bool):
    """Enable or disable all sound playback."""
    global _enabled
    _enabled = enabled


def play_start():
    """Play start-recording tone. Non-blocking."""
    if _enabled:
        try:
            winsound.PlaySound(_SOUND_START,
                               winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            log.debug("Could not play start sound")


def play_stop():
    """Play stop-recording tone. Non-blocking."""
    if _enabled:
        try:
            winsound.PlaySound(_SOUND_STOP,
                               winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            log.debug("Could not play stop sound")


def play_error():
    """Play error tone. Non-blocking."""
    if _enabled:
        try:
            winsound.PlaySound(_SOUND_ERROR,
                               winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            log.debug("Could not play error sound")
