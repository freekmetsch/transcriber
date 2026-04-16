"""Text output via clipboard paste and SendInput typing."""

import ctypes
import logging
import threading
import time

import keyboard as kb
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
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)
    finally:
        if original is not None:
            time.sleep(0.2)
            try:
                pyperclip.copy(original)
            except Exception:
                log.warning("Failed to restore clipboard")


def paste_text_streaming(text: str):
    """Paste without clipboard save/restore (for streaming mode).

    Clipboard is managed at session level by the caller.
    Uses shorter delays for streaming responsiveness.
    """
    with _paste_lock:
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.03)


def save_clipboard() -> str | None:
    """Save current clipboard contents. Call once at session start."""
    try:
        return pyperclip.paste()
    except Exception:
        log.debug("Could not save clipboard (empty or non-text content)")
        return None


def restore_clipboard(original: str | None):
    """Restore clipboard contents. Call once at session end."""
    if original is not None:
        time.sleep(0.2)
        try:
            pyperclip.copy(original)
        except Exception:
            log.warning("Failed to restore clipboard")


# --- SendInput text insertion (clipboard-free) ---

# Windows virtual key codes for modifier keys
_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12     # Alt
_VK_LWIN = 0x5B
_VK_RWIN = 0x5C
_VK_MODIFIERS = (_VK_SHIFT, _VK_CONTROL, _VK_MENU, _VK_LWIN, _VK_RWIN)

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002


# ctypes structures for SendInput (modifier release only)
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUT_UNION)]


_SendInput = ctypes.windll.user32.SendInput
_GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState


def _release_modifiers():
    """Release any held modifier keys to prevent interference with typed text."""
    for vk in _VK_MODIFIERS:
        if _GetAsyncKeyState(vk) & 0x8000:
            inp = _INPUT(type=_INPUT_KEYBOARD,
                         union=_INPUT_UNION(ki=_KEYBDINPUT(
                             wVk=vk, wScan=0, dwFlags=_KEYEVENTF_KEYUP,
                             time=0, dwExtraInfo=None)))
            _SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def type_text(text: str):
    """Type text into the active window via SendInput (keyboard.write).

    No clipboard involvement. Thread-safe (uses _paste_lock).
    Releases modifier keys before typing to prevent Ctrl/Shift interference.
    """
    with _paste_lock:
        _release_modifiers()
        time.sleep(0.05)
        kb.write(text, delay=0)


# Characters above this threshold use clipboard paste (faster for bulk)
_TYPE_THRESHOLD = 200


def _route_output(text: str, method: str, paste_fn):
    """Route text output through type or paste based on method config."""
    if method == "type" or (method == "auto" and len(text) <= _TYPE_THRESHOLD):
        try:
            type_text(text)
        except Exception:
            log.warning("type_text failed, falling back to clipboard paste")
            paste_fn(text)
    else:
        paste_fn(text)


def output_text(text: str, method: str = "auto"):
    """Output text with clipboard save/restore (batch mode)."""
    _route_output(text, method, paste_text)


def output_text_streaming(text: str, method: str = "auto"):
    """Output text without clipboard save/restore (streaming mode)."""
    _route_output(text, method, paste_text_streaming)
