"""Audio recording via sounddevice.

Recorder: batch mode — start() begins capturing, stop() returns the full buffer.
StreamingRecorder: streaming mode — VAD auto-segments speech, calls on_segment per phrase.
"""

import logging
import queue
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
        on_level=None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.on_level = on_level
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Audio status: %s", status)
        self._buffer.append(indata.copy())
        if self.on_level is not None:
            rms = float(np.sqrt(np.mean(indata ** 2)))
            try:
                self.on_level(rms)
            except Exception:
                log.exception("on_level callback raised")

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


class StreamingRecorder:
    """Records audio with VAD-based auto-chunking.

    Monitors RMS energy in the audio callback. When speech followed by a
    silence gap is detected, the speech segment is delivered via on_segment
    callback on a worker thread (not the audio callback thread).
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        device: int | str | None = None,
        silence_threshold: float = 0.01,
        silence_duration_ms: int = 600,
        min_segment_ms: int = 500,
        max_segment_s: int = 30,
        on_level=None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.silence_threshold = silence_threshold
        self.silence_duration_ms = silence_duration_ms
        self.min_segment_ms = min_segment_ms
        self.max_segment_s = max_segment_s
        self.on_level = on_level

        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

        # VAD state (only accessed from audio callback — no lock needed)
        self._in_speech = False
        self._silence_frames = 0
        self._speech_buffer: list[np.ndarray] = []
        self._speech_samples = 0

        # Segment delivery via queue + worker thread
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._on_segment = None

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Audio status: %s", status)

        chunk = indata.copy()
        rms = np.sqrt(np.mean(chunk ** 2))

        if self.on_level is not None:
            try:
                self.on_level(float(rms))
            except Exception:
                log.exception("on_level callback raised")

        # Frames needed for silence duration
        silence_frames_threshold = int(
            self.silence_duration_ms * self.sample_rate / (1000 * frames)
        )
        # Max samples before force-flush
        max_samples = self.max_segment_s * self.sample_rate
        # Min samples to accept a segment
        min_samples = int(self.min_segment_ms * self.sample_rate / 1000)

        if rms > self.silence_threshold:
            # Speech detected
            if not self._in_speech:
                self._in_speech = True
                self._silence_frames = 0
                log.debug("Speech start detected (RMS=%.4f)", rms)
            self._speech_buffer.append(chunk)
            self._speech_samples += frames
            self._silence_frames = 0

            # Force-flush if segment is too long
            if self._speech_samples >= max_samples:
                log.debug("Force-flushing segment at %ds", self.max_segment_s)
                self._flush_segment(min_samples)
        else:
            # Silence
            if self._in_speech:
                self._speech_buffer.append(chunk)
                self._speech_samples += frames
                self._silence_frames += 1

                if self._silence_frames >= silence_frames_threshold:
                    self._flush_segment(min_samples)

    def _flush_segment(self, min_samples: int):
        """Concatenate speech buffer and enqueue for processing."""
        if self._speech_buffer and self._speech_samples >= min_samples:
            audio = np.concatenate(self._speech_buffer, axis=0)
            if audio.ndim > 1:
                audio = audio[:, 0]
            duration = len(audio) / self.sample_rate
            log.info("Speech segment: %.1fs (%d samples)", duration, len(audio))
            self._queue.put(audio)
        elif self._speech_buffer:
            duration = self._speech_samples / self.sample_rate
            log.debug("Ignoring short segment (%.2fs < %dms)", duration, self.min_segment_ms)

        self._speech_buffer = []
        self._speech_samples = 0
        self._in_speech = False
        self._silence_frames = 0

    def _worker_loop(self):
        """Dequeue segments and call on_segment. Exits on None sentinel."""
        while True:
            segment = self._queue.get()
            if segment is None:
                break
            try:
                self._on_segment(segment)
            except Exception:
                log.exception("Error in on_segment callback")

    def start(self, on_segment):
        """Start streaming recording with VAD.

        Args:
            on_segment: Callable(np.ndarray) called per speech segment
                on a worker thread.
        """
        with self._lock:
            self._on_segment = on_segment
            self._in_speech = False
            self._silence_frames = 0
            self._speech_buffer = []
            self._speech_samples = 0

            # Drain any stale items from queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

            # Start worker thread
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="float32",
                    device=self.device,
                    callback=self._audio_callback,
                )
                self._stream.start()
                log.info("Streaming recording started (threshold=%.3f, silence=%dms)",
                         self.silence_threshold, self.silence_duration_ms)
            except sd.PortAudioError:
                log.exception("Failed to open audio stream — check microphone")
                self._stream = None
                self._queue.put(None)  # Stop worker

    def stop(self) -> np.ndarray | None:
        """Stop streaming. Returns any remaining buffered audio (or None)."""
        with self._lock:
            if self._stream is None:
                return None

            self._stream.stop()
            self._stream.close()
            self._stream = None

            # Extract remaining speech buffer
            remaining = None
            min_samples = int(self.min_segment_ms * self.sample_rate / 1000)
            if self._speech_buffer and self._speech_samples >= min_samples:
                remaining = np.concatenate(self._speech_buffer, axis=0)
                if remaining.ndim > 1:
                    remaining = remaining[:, 0]
                log.info("Remaining audio on stop: %.1fs", len(remaining) / self.sample_rate)

            self._speech_buffer = []
            self._speech_samples = 0
            self._in_speech = False
            self._silence_frames = 0

            # Signal worker to exit
            self._queue.put(None)
            if self._worker is not None:
                self._worker.join(timeout=5)
                self._worker = None

            log.info("Streaming recording stopped")
            return remaining
