"""Ollama LLM post-processing for dictation output.

Handles punctuation, formatting commands, and code-switch cleanup
for mixed Dutch+English transcriptions.
"""

import logging

import requests

from commands import FORMATTING_COMMANDS

log = logging.getLogger("transcriber.postprocessor")

_HEALTH_TIMEOUT = 3  # seconds
_session = requests.Session()

_SYSTEM_PROMPT_TEMPLATE = """\
You are a dictation post-processor. The user dictates in mixed Dutch and English.

Rules:
1. Add correct punctuation and capitalization.
2. Convert formatting commands to symbols:
{commands_block}
3. Preserve the EXACT language the user spoke. Do NOT translate.
4. Mixed Dutch+English in a single sentence is intentional, not an error.
5. Output ONLY the corrected text. No explanations, no commentary."""


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


# Build once at import time — the command set is static.
_SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.format(
    commands_block=_build_commands_block()
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
) -> str | None:
    """Send raw transcription to Ollama /api/chat. Returns cleaned text or None."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
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
            f"{base_url}/api/chat", json=payload, timeout=timeout
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


def postprocess_text(raw_text: str, pp_config: dict) -> str:
    """Post-process transcription via Ollama, falling back to raw text on failure.

    Args:
        raw_text: Raw Whisper transcription.
        pp_config: The "postprocessing" sub-dict from the app config.
    """
    if not pp_config.get("enabled", True):
        return raw_text

    result = _call_ollama(
        raw_text,
        model=pp_config["model"],
        base_url=pp_config["base_url"],
        timeout=pp_config["timeout"],
    )
    if result is None:
        log.info("Post-processing unavailable, returning raw Whisper text")
        return raw_text

    return result
