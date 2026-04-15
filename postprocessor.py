"""Ollama LLM post-processing for dictation output.

Handles punctuation, formatting commands, and code-switch cleanup
for mixed Dutch+English transcriptions.
"""

import logging
import time

import requests

from commands import FORMATTING_COMMANDS

log = logging.getLogger("transcriber.postprocessor")

_HEALTH_TIMEOUT = 3  # seconds
_CONNECT_TIMEOUT = 1  # seconds — fast failure detection for LAN/Tailscale
_session = requests.Session()

# Circuit breaker state for remote (primary) endpoint
_remote_healthy: bool = True
_last_remote_failure: float = 0.0
_CIRCUIT_COOLDOWN: int = 60  # seconds before re-probing a failed remote


def _is_remote_available() -> bool:
    """Return True if remote hasn't failed recently (within cooldown)."""
    if _remote_healthy:
        return True
    return (time.monotonic() - _last_remote_failure) >= _CIRCUIT_COOLDOWN


def _mark_remote_failed() -> None:
    """Mark remote as failed — circuit breaker opens."""
    global _remote_healthy, _last_remote_failure
    _remote_healthy = False
    _last_remote_failure = time.monotonic()
    log.info("Circuit breaker opened — remote marked unavailable for %ds", _CIRCUIT_COOLDOWN)


def _mark_remote_healthy() -> None:
    """Mark remote as healthy — circuit breaker closes."""
    global _remote_healthy
    if not _remote_healthy:
        log.info("Circuit breaker closed — remote recovered")
    _remote_healthy = True


_SYSTEM_PROMPT_TEMPLATE = """\
You are a dictation post-processor. The user dictates in mixed Dutch and English.

Rules:
1. Add correct punctuation and capitalization.
2. Convert formatting commands to symbols:
{commands_block}
3. Preserve the EXACT language the user spoke. Do NOT translate.
4. Mixed Dutch+English in a single sentence is intentional, not an error.
5. Output ONLY the corrected text. No explanations, no commentary.
{vocabulary_block}"""


def _build_commands_block() -> str:
    """Build the formatting-commands section for the system prompt."""
    groups: dict[str, list[str]] = {}
    for phrase, symbol in FORMATTING_COMMANDS.items():
        groups.setdefault(symbol, []).append(phrase)

    lines: list[str] = []
    for symbol, phrases in groups.items():
        # Human-readable display for whitespace symbols
        if symbol == "\n\n":
            display = "(double newline)"
        elif symbol == "\n":
            display = "(actual newline)"
        else:
            display = symbol
        quoted = " / ".join(f'"{p}"' for p in phrases)
        lines.append(f"   - {quoted} \u2192 {display}")
    return "\n".join(lines)


# Build the commands block once at import time — the command set is static.
_COMMANDS_BLOCK = _build_commands_block()


def _build_system_prompt(vocabulary_text: str = "") -> str:
    """Build the full system prompt, optionally including vocabulary terms."""
    if vocabulary_text:
        vocab_block = (
            "\n6. The user has these custom vocabulary terms. "
            "Prefer these exact spellings when the audio is ambiguous:\n"
            + vocabulary_text
        )
    else:
        vocab_block = ""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        commands_block=_COMMANDS_BLOCK,
        vocabulary_block=vocab_block,
    )


def ollama_health_check(base_url: str) -> bool:
    """Return True if the Ollama server is reachable."""
    try:
        r = _session.get(f"{base_url}/api/tags", timeout=_HEALTH_TIMEOUT)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def _call_ollama(
    raw_text: str,
    *,
    model: str,
    base_url: str,
    timeout: int,
    vocabulary_text: str = "",
) -> str | None:
    """Send raw transcription to Ollama /api/chat. Returns cleaned text or None."""
    system_prompt = _build_system_prompt(vocabulary_text)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ],
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.1,
            "num_ctx": 2048,
        },
    }
    try:
        r = _session.post(
            f"{base_url}/api/chat", json=payload, timeout=(_CONNECT_TIMEOUT, timeout)
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()
    except requests.ConnectionError:
        log.warning("Ollama not reachable at %s", base_url)
        return None
    except requests.Timeout:
        log.warning("Ollama timed out after %ds", timeout)
        return None
    except requests.HTTPError as e:
        log.error("Ollama HTTP error: %s", e)
        return None
    except Exception:
        log.exception("Unexpected error during post-processing")
        return None


def postprocess_text(raw_text: str, pp_config: dict, vocabulary_text: str = "") -> str:
    """Post-process transcription via Ollama, with primary→fallback chain.

    Tries the primary endpoint first. If a fallback_url is configured and the
    primary fails, tries the fallback. Only returns raw text if both fail.

    Args:
        raw_text: Raw Whisper transcription.
        pp_config: The "postprocessing" sub-dict from the app config.
        vocabulary_text: Formatted vocabulary list from the brain DB.
    """
    if not pp_config.get("enabled", True):
        return raw_text

    fallback_url = pp_config.get("fallback_url")
    call_kwargs = dict(
        model=pp_config["model"],
        timeout=pp_config["timeout"],
        vocabulary_text=vocabulary_text,
    )

    # Try primary (skip if circuit breaker is open AND fallback exists)
    if fallback_url is None or _is_remote_available():
        result = _call_ollama(raw_text, base_url=pp_config["base_url"], **call_kwargs)
        if result is not None:
            _mark_remote_healthy()
            return result
        if fallback_url is not None:
            _mark_remote_failed()

    # Try fallback
    if fallback_url:
        log.info("Primary Ollama unavailable, using fallback at %s", fallback_url)
        result = _call_ollama(raw_text, base_url=fallback_url, **call_kwargs)
        if result is not None:
            return result

    # Both failed (or no fallback configured)
    log.warning("All Ollama endpoints failed, returning raw Whisper text")
    return raw_text
