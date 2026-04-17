"""Groq two-call cloud dictation: Whisper STT → Llama text polish.

Unlike audio-chat models (openai/gpt-audio) that occasionally reply
conversationally to ambiguous audio, Groq's STT endpoint can only emit
transcribed text — the hallucination class is eliminated by construction.
The second call polishes the raw transcript against the system prompt
(vocabulary bias + formatting commands). If the polish call fails but the
STT succeeded, the raw transcript is returned as graceful degradation.
"""

import logging

import numpy as np
import requests

from cloud_dictator import (
    _CONNECT_TIMEOUT,
    CloudProvider,
    CloudUnavailable,
    _CircuitBreaker,
)

log = logging.getLogger("transcriber.groq_dictator")


class _PolishSoftFailure(Exception):
    """Polish-step failure that should fall back to raw STT text, not the local path."""


class GroqDictator(_CircuitBreaker, CloudProvider):
    """Two-call cloud: Groq Whisper STT, then Groq Llama text polish."""

    def __init__(
        self,
        api_key: str,
        *,
        stt_model: str = "whisper-large-v3-turbo",
        polish_model: str = "llama-3.3-70b-versatile",
        base_url: str = "https://api.groq.com/openai/v1",
        stt_timeout: float = 3.0,
        polish_timeout: float = 3.0,
        failure_threshold: int = 3,
        cooldown_s: float = 60.0,
    ):
        super().__init__(failure_threshold=failure_threshold, cooldown_s=cooldown_s)
        self._stt_model = stt_model
        self._polish_model = polish_model
        self._base_url = base_url.rstrip("/")
        self._stt_timeout = stt_timeout
        self._polish_timeout = polish_timeout
        self._session = requests.Session()
        # STT omits Content-Type so requests can compute the multipart boundary.
        self._stt_headers = {"Authorization": f"Bearer {api_key}"}
        self._polish_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def dictate(self, audio: np.ndarray, *, system_prompt: str) -> str:
        if not self._breaker_allows():
            raise CloudUnavailable("breaker open")

        try:
            wav = self._wav_bytes(audio)
        except Exception as exc:
            log.exception("cloud: audio serialization failed")
            self._trip_breaker()
            raise CloudUnavailable("serialization") from exc

        raw = self._call_stt(wav).strip()
        if not raw:
            # Empty/whitespace transcript — skip polish, don't burn a round-trip.
            self._reset_breaker()
            return ""

        try:
            polished = self._call_polish(raw, system_prompt=system_prompt)
        except _PolishSoftFailure as exc:
            log.info("cloud: polish soft-failed (%s) — returning raw: %r", exc, raw[:80])
            self._reset_breaker()
            return raw

        self._reset_breaker()
        return polished

    def _call_stt(self, wav: bytes) -> str:
        files = {
            "file": ("audio.wav", wav, "audio/wav"),
            "model": (None, self._stt_model),
            "response_format": (None, "text"),
        }
        try:
            r = self._session.post(
                f"{self._base_url}/audio/transcriptions",
                headers=self._stt_headers,
                files=files,
                timeout=(_CONNECT_TIMEOUT, self._stt_timeout),
            )
        except requests.ConnectionError as exc:
            log.warning("cloud: stt connection error (%s)", exc)
            self._trip_breaker()
            raise CloudUnavailable("stt-connection") from exc
        except requests.Timeout as exc:
            log.warning("cloud: stt timed out after %.1fs", self._stt_timeout)
            self._trip_breaker()
            raise CloudUnavailable("stt-timeout") from exc

        self._check_auth_and_rate(r, label="stt")

        if not r.ok:
            log.warning("cloud: stt HTTP %d — %s", r.status_code, r.text[:200])
            self._trip_breaker()
            raise CloudUnavailable(f"stt-http-{r.status_code}")

        return r.text or ""

    def _call_polish(self, raw_text: str, *, system_prompt: str) -> str:
        """Soft-fails via `_PolishSoftFailure` on timeout/5xx; hard-fails on auth/rate-limit."""
        payload = {
            "model": self._polish_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_text},
            ],
        }
        try:
            r = self._session.post(
                f"{self._base_url}/chat/completions",
                headers=self._polish_headers,
                json=payload,
                timeout=(_CONNECT_TIMEOUT, self._polish_timeout),
            )
        except requests.ConnectionError as exc:
            raise _PolishSoftFailure(f"connection: {exc}") from exc
        except requests.Timeout as exc:
            raise _PolishSoftFailure(f"timeout after {self._polish_timeout:.1f}s") from exc

        # Auth/rate-limit still hard-fail — same key feeds STT, so it's a cascade-wide signal.
        self._check_auth_and_rate(r, label="polish")

        if not r.ok:
            raise _PolishSoftFailure(f"http-{r.status_code}: {r.text[:200]}")

        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise _PolishSoftFailure(f"malformed response: {exc}") from exc

        if not text or not text.strip():
            raise _PolishSoftFailure("empty response")

        return text.strip()
