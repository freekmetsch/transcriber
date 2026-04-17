"""Audio recording via sounddevice.

Recorder: batch mode — start() begins capturing, stop() returns the full buffer.
StreamingRecorder: streaming mode — captures at mic-native rate, resamples to
16 kHz, feeds 512-sample frames to a VAD (Silero or Energy), and calls
on_segment per phrase. DC-offset + peak-normalization applied per segment.
"""

import logging
import math
import queue
import threading
from collections import deque
from math import gcd

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

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

    def cancel(self):
        """Stop capturing and discard the buffer. Returns nothing."""
        with self._lock:
            if self._stream is None:
                return
            self._stream.stop()
            self._stream.close()
            self._stream = None
            self._buffer = []
        log.info("Recording cancelled (buffer discarded)")


class StreamingRecorder:
    """Records audio with VAD-based auto-chunking.

    Captures at mic-native samplerate, downmixes to mono, resamples to 16 kHz
    (via scipy polyphase), feeds fixed-size frames to the configured VAD
    (Silero by default). Segment delivery happens on a worker thread.

    Per-segment conditioning: DC-offset removal + peak normalization (up to
    0.3 peak for soft speech) applied once before enqueueing.
    """

    def __init__(
        self,
        *,
        vad,
        channels: int = 1,
        device: int | str | None = None,
        target_sample_rate: int = 16000,
        preroll_ms: int = 300,
        min_segment_ms: int = 500,
        max_segment_s: int = 30,
        on_level=None,
    ):
        self._vad = vad
        self._chunk_samples = int(getattr(vad, "REQUIRED_CHUNK_SAMPLES", 512))
        self._target_sr = int(getattr(vad, "SAMPLE_RATE", target_sample_rate))
        self._channels_requested = channels
        self._device = device
        self._min_segment_samples = int(min_segment_ms * self._target_sr / 1000)
        self._max_segment_samples = int(max_segment_s * self._target_sr)
        # Store pre-roll as a deque of fixed-size chunks — avoids per-callback
        # tolist()/boxing that a per-sample deque would incur.
        preroll_samples = int(preroll_ms * self._target_sr / 1000)
        self._preroll_chunks_max = max(1, math.ceil(preroll_samples / self._chunk_samples))
        self.on_level = on_level

        self._mic_sr: int = self._target_sr
        self._input_channels: int = 1
        self._resample_up: int = 1
        self._resample_down: int = 1
        self._needs_resample: bool = False

        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._on_segment = None
        self._cancelled = False

        # Callback-thread-only state.
        self._preroll_buf: deque[np.ndarray] = deque(maxlen=self._preroll_chunks_max)
        self._pending: list[np.ndarray] = []
        self._pending_total: int = 0
        self._in_speech: bool = False
        self._speech_chunks: list[np.ndarray] = []
        self._speech_samples: int = 0

    def _reset_callback_state(self):
        self._preroll_buf.clear()
        self._pending = []
        self._pending_total = 0
        self._in_speech = False
        self._speech_chunks = []
        self._speech_samples = 0

    def _detect_mic_params(self):
        """Query device default samplerate + channels. Falls back to target_sr on failure."""
        try:
            info = sd.query_devices(self._device, "input")
            self._mic_sr = int(info["default_samplerate"])
            max_ch = int(info["max_input_channels"])
            self._input_channels = max(1, min(self._channels_requested or 1, max_ch))
        except Exception:
            log.exception("Failed to query device — using target sr/channels")
            self._mic_sr = self._target_sr
            self._input_channels = max(1, self._channels_requested or 1)

        if self._mic_sr != self._target_sr:
            g = gcd(self._target_sr, self._mic_sr)
            self._resample_up = self._target_sr // g
            self._resample_down = self._mic_sr // g
            self._needs_resample = True
        else:
            self._resample_up = self._resample_down = 1
            self._needs_resample = False

        log.info(
            "Mic: sr=%d ch=%d → %d Hz (resample %d/%d)",
            self._mic_sr, self._input_channels, self._target_sr,
            self._resample_up, self._resample_down,
        )

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Audio status: %s", status)

        if indata.ndim > 1 and indata.shape[1] > 1:
            mono = indata.mean(axis=1).astype(np.float32)
        else:
            mono = (indata[:, 0] if indata.ndim > 1 else indata).astype(np.float32)

        if self.on_level is not None:
            try:
                self.on_level(float(np.sqrt(np.mean(mono ** 2))))
            except Exception:
                log.exception("on_level callback raised")

        if self._needs_resample:
            resampled = resample_poly(mono, self._resample_up, self._resample_down).astype(np.float32)
        else:
            resampled = mono

        self._pending.append(resampled)
        self._pending_total += resampled.size

        if self._pending_total < self._chunk_samples:
            return

        flat = np.concatenate(self._pending)
        idx = 0
        while idx + self._chunk_samples <= flat.size:
            chunk = flat[idx:idx + self._chunk_samples]
            idx += self._chunk_samples
            self._process_chunk(chunk)

        remainder = flat[idx:] if idx < flat.size else np.empty(0, dtype=np.float32)
        self._pending = [remainder] if remainder.size else []
        self._pending_total = remainder.size

    def _process_chunk(self, chunk: np.ndarray) -> None:
        """Feed one chunk through pre-roll + VAD + segment accumulator."""
        # Append before VAD so a 'start' snapshot includes this chunk.
        self._preroll_buf.append(chunk)

        try:
            event = self._vad.feed(chunk)
        except Exception:
            log.exception("VAD feed raised — resetting VAD")
            try:
                self._vad.reset()
            except Exception:
                log.exception("VAD reset raised")
            event = None

        if event == "start" and not self._in_speech:
            self._in_speech = True
            preroll_snapshot = (
                np.concatenate(list(self._preroll_buf))
                if self._preroll_buf else np.empty(0, dtype=np.float32)
            )
            self._speech_chunks = [preroll_snapshot]
            self._speech_samples = preroll_snapshot.size
            log.debug(
                "vad: speech start p=%.2f pre_roll_ms=%d",
                float(getattr(self._vad, "last_speech_prob", 0.0)),
                int(preroll_snapshot.size * 1000 / self._target_sr),
            )
            return

        if event == "end" and self._in_speech:
            # Include this chunk as the tail so the segment covers the reported end.
            self._speech_chunks.append(chunk)
            self._speech_samples += self._chunk_samples
            duration = self._speech_samples / self._target_sr
            log.debug(
                "vad: speech end duration=%.2fs pad_ms=%d",
                duration, int(getattr(self._vad, "speech_pad_ms", 0)),
            )
            self._flush_segment()
            return

        if self._in_speech:
            self._speech_chunks.append(chunk)
            self._speech_samples += self._chunk_samples
            if self._speech_samples >= self._max_segment_samples:
                log.debug("Force-flushing segment at %.1fs",
                          self._speech_samples / self._target_sr)
                self._flush_segment()

    @staticmethod
    def _condition(audio: np.ndarray) -> tuple[np.ndarray, float]:
        """DC removal + soft-gain. Returns (conditioned_audio, original_peak)."""
        audio = audio - float(audio.mean())
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        # Only amplify audible-but-soft signals; never amplify near-silence.
        if 0.01 <= peak < 0.3:
            audio = audio * (0.3 / peak)
        return audio, peak

    def _flush_segment(self) -> None:
        """Concatenate, condition, and enqueue if long enough."""
        if self._speech_chunks and self._speech_samples >= self._min_segment_samples:
            audio, peak = self._condition(np.concatenate(self._speech_chunks))
            log.info(
                "Speech segment: %.1fs (%d samples, peak=%.3f)",
                audio.size / self._target_sr, audio.size, peak,
            )
            self._queue.put(audio)
        elif self._speech_chunks:
            min_ms = int(self._min_segment_samples * 1000 / self._target_sr)
            log.debug(
                "Ignoring short segment (%.2fs < %dms)",
                self._speech_samples / self._target_sr, min_ms,
            )

        self._speech_chunks = []
        self._speech_samples = 0
        self._in_speech = False
        # Pre-roll keeps flowing — it holds the last N ms regardless of speech state.

    def _worker_loop(self):
        """Dequeue segments and call on_segment. Exits on None sentinel or cancel."""
        while True:
            segment = self._queue.get()
            if segment is None or self._cancelled:
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
            self._reset_callback_state()
            self._cancelled = False
            try:
                self._vad.reset()
            except Exception:
                log.exception("VAD reset at start raised")

            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

            self._detect_mic_params()

            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

            try:
                self._stream = sd.InputStream(
                    samplerate=self._mic_sr,
                    channels=self._input_channels,
                    dtype="float32",
                    device=self._device,
                    callback=self._audio_callback,
                )
                self._stream.start()
                preroll_ms = int(self._preroll_chunks_max * self._chunk_samples * 1000 / self._target_sr)
                log.info(
                    "Streaming started (mic=%d Hz, ch=%d, target=%d Hz, chunk=%d, preroll=%dms)",
                    self._mic_sr, self._input_channels, self._target_sr,
                    self._chunk_samples, preroll_ms,
                )
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

            remaining = None
            if self._speech_chunks and self._speech_samples >= self._min_segment_samples:
                remaining, _peak = self._condition(np.concatenate(self._speech_chunks))
                log.info("Remaining audio on stop: %.1fs", len(remaining) / self._target_sr)

            self._reset_callback_state()
            try:
                self._vad.reset()
            except Exception:
                log.exception("VAD reset at stop raised")

            self._queue.put(None)
            if self._worker is not None:
                self._worker.join(timeout=5)
                self._worker = None

            log.info("Streaming recording stopped")
            return remaining

    def cancel(self):
        """Stop streaming and discard all buffered audio without flushing."""
        with self._lock:
            if self._stream is None:
                return
            self._cancelled = True
            self._stream.stop()
            self._stream.close()
            self._stream = None

            self._reset_callback_state()
            try:
                self._vad.reset()
            except Exception:
                log.exception("VAD reset at cancel raised")

            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._queue.put(None)
            worker, self._worker = self._worker, None

        # Join outside the lock: the worker calls on_segment → app code, which
        # may eventually call back into recorder methods that take this lock.
        if worker is not None:
            worker.join(timeout=5)
        log.info("Streaming recording cancelled (audio discarded)")
