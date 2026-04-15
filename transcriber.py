"""Speech-to-text via faster-whisper. Handles model loading and transcription."""

import logging

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger("transcriber.transcriber")


class Transcriber:
    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: WhisperModel | None = None

    def load_model(self):
        """Load the Whisper model. Falls back to CPU if CUDA fails."""
        log.info(
            "Loading faster-whisper model '%s' (device=%s, compute_type=%s)",
            self.model_size,
            self.device,
            self.compute_type,
        )
        try:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        except Exception:
            if self.device == "cuda":
                log.warning("CUDA failed, falling back to CPU with int8")
                self.device = "cpu"
                self.compute_type = "int8"
                self._model = WhisperModel(
                    self.model_size, device="cpu", compute_type="int8"
                )
            else:
                raise
        log.info("Model loaded successfully")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 16 kHz mono numpy array. Returns the recognized text."""
        if self._model is None:
            raise RuntimeError("Model not loaded — call load_model() first")

        segments, info = self._model.transcribe(
            audio,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        log.info(
            "Detected language: %s (probability %.2f)",
            info.language,
            info.language_probability,
        )

        return " ".join(seg.text for seg in segments).strip()
