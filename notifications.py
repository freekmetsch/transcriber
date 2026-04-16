"""Windows toast notifications for brain events.

Uses winotify for native Windows 10/11 toast notifications.
If winotify is not installed, all calls are silent no-ops.
"""

import logging

log = logging.getLogger("transcriber.notifications")

try:
    from winotify import Notification, audio
    _AVAILABLE = True
    log.debug("winotify available — toast notifications enabled")
except ImportError:
    _AVAILABLE = False
    log.info("winotify not installed — toast notifications disabled (pip install winotify)")

_APP_ID = "Personal Transcriber"

# Track one-per-session warnings to avoid notification spam
_ollama_warned = False


def _send(title: str, msg: str):
    """Send a toast notification. No-op if winotify unavailable."""
    if not _AVAILABLE:
        return
    try:
        toast = Notification(
            app_id=_APP_ID,
            title=title,
            msg=msg,
        )
        toast.set_audio(audio.Silent, loop=False)
        toast.show()
    except Exception:
        log.debug("Toast notification failed", exc_info=True)


def notify_auto_learned(term: str, was: str, correction_count: int):
    """Notify that a term was auto-learned from repeated corrections."""
    _send(
        "Brain learned a new term",
        f"{term} (was: {was}) — after {correction_count} corrections",
    )
    log.info("Toast: auto-learned '%s' (was: '%s')", term, was)


def notify_ollama_fallback():
    """Notify that Ollama is unavailable (once per session)."""
    global _ollama_warned
    if _ollama_warned:
        return
    _ollama_warned = True
    _send(
        "Post-processing unavailable",
        "All Ollama endpoints unreachable — using raw transcription text",
    )
    log.info("Toast: Ollama fallback warning")


def notify_vocab_imported(count: int, source: str):
    """Notify that vocabulary was imported."""
    _send(
        "Vocabulary imported",
        f"Imported {count} terms from {source}",
    )
    log.info("Toast: imported %d terms from %s", count, source)


def notify_vocab_added(term: str):
    """Notify that a vocabulary term was manually added."""
    _send(
        "Term added to vocabulary",
        term,
    )


# --- App-level notifications (not brain-gated) ---

def notify_startup(hotkey: str):
    """Notify that the transcriber is ready."""
    _send("Transcriber ready", f"Press {hotkey} to dictate")
    log.info("Toast: startup ready")


def notify_info(title: str, detail: str = ""):
    """Generic info toast for one-off success/status events."""
    _send(title, detail)
    log.info("Toast: info — %s: %s", title, detail)


def notify_error(title: str, detail: str):
    """Notify about a transcription or pipeline error."""
    _send(title, detail)
    log.info("Toast: error — %s: %s", title, detail)


def notify_guard_blocked(class_name: str):
    """Notify that recording was blocked (no text field detected)."""
    _send(
        "No text field detected",
        f"Click a text field first (window class: {class_name})",
    )
    log.info("Toast: guard blocked (%s)", class_name)


def is_available() -> bool:
    """Check if toast notifications are available."""
    return _AVAILABLE
