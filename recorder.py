"""Audio recording via sounddevice. Push-to-talk: start() begins capturing, stop() returns the buffer."""

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger("transcriber.recorder")


class Recorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        device: int | str | None = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Audio status: %s", status)
        self._buffer.append(indata.copy())

    def start(self):
        """Begin capturing audio from the microphone."""
        with self._lock:
            self._buffer = []
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="float32",
                    device=self.device,
                    callback=self._audio_callback,
                )
                self._stream.start()
            except sd.PortAudioError:
                log.exception("Failed to open audio stream — check microphone")
                self._stream = None

    def stop(self) -> np.ndarray | None:
        """Stop capturing and return the recorded audio as a 1D float32 numpy array."""
        with self._lock:
            if self._stream is None:
                return None
            self._stream.stop()
            self._stream.close()
            self._stream = None
            if not self._buffer:
                return None
            audio = np.concatenate(self._buffer, axis=0)
            self._buffer = []

        # Flatten to mono if needed
        if audio.ndim > 1:
            audio = audio[:, 0]

        duration = len(audio) / self.sample_rate
        log.info("Captured %.1f seconds of audio", duration)
        return audio
