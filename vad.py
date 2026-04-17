"""Voice Activity Detection backends + factory.

Two implementations behind a common protocol:
  SileroStreamingVAD — silero-vad ONNX, production default.
  EnergyVAD          — RMS-threshold fallback used if Silero fails to load.

Both implement:
  feed(chunk_512_float32) -> "start" | "end" | None
  reset()
  last_speech_prob : float                # most recent prob (or RMS)
  REQUIRED_CHUNK_SAMPLES, SAMPLE_RATE     # class constants the recorder reads

`make_vad(config)` constructs a VAD from the `streaming.vad` config dict and
gracefully falls back to `EnergyVAD` on Silero import/load failure.
"""

import logging
from typing import Optional

import numpy as np

log = logging.getLogger("transcriber.vad")

_SAMPLE_RATE = 16000
_SILERO_CHUNK = 512          # Silero v5 requires exactly 512 samples at 16 kHz.


class SileroStreamingVAD:
    """silero-vad VADIterator wrapper with per-chunk probability capture."""

    REQUIRED_CHUNK_SAMPLES = _SILERO_CHUNK
    SAMPLE_RATE = _SAMPLE_RATE

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_ms: int = 600,
        speech_pad_ms: int = 120,
    ):
        import torch
        from silero_vad import load_silero_vad, VADIterator

        self._torch = torch
        self._model = load_silero_vad(onnx=True)
        self._vad_iter = VADIterator(
            self._model,
            threshold=threshold,
            sampling_rate=_SAMPLE_RATE,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._threshold = threshold
        self._min_silence_ms = min_silence_ms
        self._speech_pad_ms = speech_pad_ms
        self.last_speech_prob: float = 0.0

    def feed(self, chunk: np.ndarray) -> Optional[str]:
        if chunk.shape[0] != _SILERO_CHUNK:
            raise ValueError(
                f"SileroStreamingVAD needs {_SILERO_CHUNK} samples, got {chunk.shape[0]}"
            )
        tensor = self._torch.from_numpy(chunk.copy())
        # Separate forward pass to capture the probability — VADIterator runs
        # the model again internally (~0.3 ms extra on CPU); the alternative
        # is reaching into VADIterator's private state, which is unstable
        # across silero-vad versions.
        self.last_speech_prob = float(self._model(tensor, _SAMPLE_RATE).item())
        event = self._vad_iter(tensor)
        if event is None:
            return None
        if "start" in event:
            return "start"
        if "end" in event:
            return "end"
        return None

    def reset(self) -> None:
        self._vad_iter.reset_states()

    @property
    def speech_pad_ms(self) -> int:
        return self._speech_pad_ms

    @property
    def min_silence_ms(self) -> int:
        return self._min_silence_ms


class EnergyVAD:
    """RMS-threshold fallback. Same feed()/reset() protocol as SileroStreamingVAD."""

    REQUIRED_CHUNK_SAMPLES = _SILERO_CHUNK
    SAMPLE_RATE = _SAMPLE_RATE

    def __init__(
        self,
        threshold: float = 0.01,
        min_silence_ms: int = 600,
        speech_pad_ms: int = 0,
    ):
        self._threshold = threshold
        self._min_silence_ms = min_silence_ms
        self._speech_pad_ms = speech_pad_ms
        self._silence_target_samples = int(min_silence_ms * _SAMPLE_RATE / 1000)
        self._in_speech = False
        self._silent_samples = 0
        # Named to match SileroStreamingVAD so the recorder reads one attribute;
        # for EnergyVAD this actually holds the most recent RMS, not a prob.
        self.last_speech_prob: float = 0.0

    def feed(self, chunk: np.ndarray) -> Optional[str]:
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        self.last_speech_prob = rms
        if rms > self._threshold:
            if not self._in_speech:
                self._in_speech = True
                self._silent_samples = 0
                return "start"
            self._silent_samples = 0
            return None
        if self._in_speech:
            self._silent_samples += chunk.shape[0]
            if self._silent_samples >= self._silence_target_samples:
                self._in_speech = False
                self._silent_samples = 0
                return "end"
        return None

    def reset(self) -> None:
        self._in_speech = False
        self._silent_samples = 0

    @property
    def speech_pad_ms(self) -> int:
        return self._speech_pad_ms

    @property
    def min_silence_ms(self) -> int:
        return self._min_silence_ms


def make_vad(vad_config: dict):
    """Build a VAD from the `streaming.vad` config dict.

    Silero is the default; any load failure (missing deps, ONNX runtime quirk,
    etc.) degrades to EnergyVAD with a warning so the app stays usable.
    """
    engine = (vad_config.get("engine") or "silero").lower()
    min_silence_ms = int(vad_config.get("min_silence_ms", 600))
    speech_pad_ms = int(vad_config.get("speech_pad_ms", 120))

    if engine == "energy":
        threshold = float(vad_config.get("threshold", 0.01))
        log.info(
            "vad: engine=energy threshold=%.3f min_silence_ms=%d",
            threshold, min_silence_ms,
        )
        return EnergyVAD(
            threshold=threshold,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )

    threshold = float(vad_config.get("threshold", 0.5))
    try:
        vad = SileroStreamingVAD(
            threshold=threshold,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        log.info(
            "vad: engine=silero threshold=%.2f min_silence_ms=%d speech_pad_ms=%d",
            threshold, min_silence_ms, speech_pad_ms,
        )
        return vad
    except Exception:
        log.exception("vad: silero failed to load — falling back to EnergyVAD")
        return EnergyVAD(
            threshold=0.01,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
