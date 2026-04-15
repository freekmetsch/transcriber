"""Text output via clipboard paste. Saves and restores clipboard contents."""

import logging
import threading
import time

import pyautogui
import pyperclip

log = logging.getLogger("transcriber.output")

pyautogui.FAILSAFE = False

# Serialize clipboard+paste to prevent concurrent transcriptions from colliding
_paste_lock = threading.Lock()


def paste_text(text: str):
    """Copy text to clipboard, paste it into the active window, then restore the original clipboard."""
    with _paste_lock:
        _paste_text_locked(text)


def _paste_text_locked(text: str):
    original = None
    try:
        original = pyperclip.paste()
    except Exception:
        log.debug("Could not read clipboard (empty or non-text content)")

    try:
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)
    finally:
        if original is not None:
            time.sleep(0.2)
            try:
                pyperclip.copy(original)
            except Exception:
                log.warning("Failed to restore clipboard")
