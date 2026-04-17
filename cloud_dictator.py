"""Cloud dictation provider interface + OpenRouter audio-chat implementation.

`CloudProvider` is the abstract base every cascade-compatible dictation backend
implements. `_CircuitBreaker` holds the shared failure-tracking / rate-limit
state so each concrete provider (OpenRouter, Groq, ...) inherits identical
breaker semantics. `OpenRouterDictator` is the one-call audio-chat path — it
uploads audio + system prompt and receives polished text in a single request.
"""

import base64
import io
import logging
import threading
import time

import numpy as np
import requests

log = logging.getLogger("transcriber.cloud_dictator")

_CONNECT_TIMEOUT = 1.5


class CloudUnavailable(Exception):
    """Raised when the cloud path is unreachable and the caller should fall back."""


class _CircuitBreaker:
    """Shared failure tracking for cloud providers.

    Concrete providers call `_breaker_allows()` before issuing a request and
    `_trip_breaker()` / `_reset_breaker()` depending on outcome. A single
    invalid-auth response permanently disables the breaker until restart.
    """

    def __init__(self, *, failure_threshold: int = 3, cooldown_s: float = 60.0):
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._failures: int = 0
        self._breaker_open_until: float = 0.0
        self._key_invalid: bool = False

    def _breaker_allows(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._key_invalid:
                return False
            if now < self._breaker_open_until:
                return False
            return True

    def _trip_breaker(self, cooldown_s: float | None = None) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                duration = cooldown_s if cooldown_s is not None else self._cooldown_s
                self._breaker_open_until = time.monotonic() + duration
                log.warning(
                    "cloud: circuit breaker opened for %.0fs (after %d failures)",
                    duration,
                    self._failures,
                )

    def _reset_breaker(self) -> None:
        with self._lock:
            if self._failures or self._breaker_open_until:
                log.info("cloud: circuit breaker closed — recovered")
            self._failures = 0
            self._breaker_open_until = 0.0

    def _mark_key_invalid(self) -> None:
        with self._lock:
            if not self._key_invalid:
                log.error("cloud: invalid API key — cascade disabled until restart")
            self._key_invalid = True

    def _force_breaker_open(self, duration_s: float) -> None:
        with self._lock:
            self._breaker_open_until = time.monotonic() + duration_s

    @staticmethod
    def _parse_retry_after(value: str | None) -> float:
        if not value:
            return 60.0
        try:
            return max(1.0, float(value))
        except ValueError:
            return 60.0

    def _check_auth_and_rate(self, r: requests.Response, *, label: str) -> None:
        """Translate 401/429 into breaker effects. Other statuses are caller's problem."""
        if r.status_code == 401:
            self._mark_key_invalid()
            raise CloudUnavailable(f"{label}-auth")
        if r.status_code == 429:
            retry_after = self._parse_retry_after(r.headers.get("Retry-After"))
            log.warning("cloud: %s rate-limited (Retry-After=%s)", label, retry_after)
            self._force_breaker_open(retry_after)
            raise CloudUnavailable(f"{label}-rate-limited")


class CloudProvider:
    """Abstract cloud dictation interface. Implementations return polished text."""

    def dictate(self, audio: np.ndarray, *, system_prompt: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _wav_bytes(audio: np.ndarray) -> bytes:
        """Serialize a 16 kHz float32 mono numpy array to PCM_16 WAV bytes."""
        import soundfile  # Lazy import — avoids startup cost when cloud disabled.

        buf = io.BytesIO()
        soundfile.write(buf, audio, 16000, format="WAV", subtype="PCM_16")
        return buf.getvalue()


class OpenRouterDictator(_CircuitBreaker, CloudProvider):
    """Post audio to OpenRouter chat/completions with an `input_audio` message.

    The remote model both transcribes and applies the system-prompt rules
    (punctuation, formatting commands, personal vocabulary). Returns the polished
    text directly — no separate post-processing step.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "openai/gpt-audio",
        base_url: str = "https://openrouter.ai/api/v1",
        referer: str = "https://github.com/freekmetsch/transcriber",
        title: str = "Transcriber",
        timeout: float = 2.0,
        failure_threshold: int = 3,
        cooldown_s: float = 60.0,
    ):
        super().__init__(failure_threshold=failure_threshold, cooldown_s=cooldown_s)
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._referer = referer
        self._title = title
        self._timeout = timeout
        self._session = requests.Session()

    def dictate(self, audio: np.ndarray, *, system_prompt: str) -> str:
        """Return polished text for `audio`. Raises `CloudUnavailable` on any failure."""
        if not self._breaker_allows():
            raise CloudUnavailable("breaker open")

        try:
            wav = self._wav_bytes(audio)
        except Exception as exc:
            log.exception("cloud: audio serialization failed")
            self._trip_breaker()
            raise CloudUnavailable("serialization") from exc

        payload = {
            "model": self._model,
            "modalities": ["text"],
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(wav).decode("ascii"),
                                "format": "wav",
                            },
                        },
                    ],
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": self._referer,
            "X-Title": self._title,
            "Content-Type": "application/json",
        }

        try:
            r = self._session.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=(_CONNECT_TIMEOUT, self._timeout),
            )
        except requests.ConnectionError as exc:
            log.warning("cloud: connection error (%s)", exc)
            self._trip_breaker()
            raise CloudUnavailable("connection") from exc
        except requests.Timeout as exc:
            log.warning("cloud: timed out after %.1fs", self._timeout)
            self._trip_breaker()
            raise CloudUnavailable("timeout") from exc

        self._check_auth_and_rate(r, label="openrouter")

        if not r.ok:
            log.warning("cloud: HTTP %d — %s", r.status_code, r.text[:200])
            self._trip_breaker()
            raise CloudUnavailable(f"http-{r.status_code}")

        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            log.warning("cloud: malformed response (%s)", exc)
            self._trip_breaker()
            raise CloudUnavailable("malformed") from exc

        if not text or not text.strip():
            log.warning("cloud: empty response")
            self._trip_breaker()
            raise CloudUnavailable("empty")

        self._reset_breaker()
        return text.strip()
