"""Text field detection and window targeting via Win32 ctypes.

Pure ctypes — no external dependencies. Provides:
- check_text_field(): detect if the focused control is an editable text field
- capture_target(): save the foreground window HWND for later refocus
- refocus_target(): bring a saved window back to foreground and optionally return
- is_target_alive(): check if a saved HWND is still valid
"""

import ctypes
import ctypes.wintypes
import logging

log = logging.getLogger("transcriber.focus_guard")

# --- Win32 API bindings ---

user32 = ctypes.windll.user32

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.restype = ctypes.wintypes.HWND

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

GetClassName = user32.GetClassNameW
GetClassName.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
GetClassName.restype = ctypes.c_int

IsWindow = user32.IsWindow
IsWindow.argtypes = [ctypes.wintypes.HWND]
IsWindow.restype = ctypes.wintypes.BOOL

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
SetForegroundWindow.restype = ctypes.wintypes.BOOL

AttachThreadInput = user32.AttachThreadInput
AttachThreadInput.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.wintypes.BOOL]
AttachThreadInput.restype = ctypes.wintypes.BOOL

GetCurrentThreadId = ctypes.windll.kernel32.GetCurrentThreadId
GetCurrentThreadId.restype = ctypes.wintypes.DWORD


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("hwndActive", ctypes.wintypes.HWND),
        ("hwndFocus", ctypes.wintypes.HWND),
        ("hwndCapture", ctypes.wintypes.HWND),
        ("hwndMenuOwner", ctypes.wintypes.HWND),
        ("hwndMoveSize", ctypes.wintypes.HWND),
        ("hwndCaret", ctypes.wintypes.HWND),
        ("rcCaret", ctypes.wintypes.RECT),
    ]


GetGUIThreadInfo = user32.GetGUIThreadInfo
GetGUIThreadInfo.argtypes = [ctypes.wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
GetGUIThreadInfo.restype = ctypes.wintypes.BOOL

# --- Class name heuristics ---

# Known editable control classes (case-insensitive matching)
_EDITABLE_CLASSES = {
    "edit",
    "richedit20w",
    "richedit50w",
    "richeditd2dpt",
    "scintilla",
    "_wwg",                 # Microsoft Word
    "inet_machtmled",       # IE HTML editor
    "texteditbox",
    "tkinputwidget",        # Tk Text/Entry
}

# Browser/Electron renderer classes — assume editable (permissive)
_BROWSER_CLASSES = {
    "chrome_renderwidgethosthwnd",
    "mozillawindowclass",
    "internet explorer_server",
    "webviewhost",
    "cefbrowserwindow",
}

# Known non-text windows — block recording
_BLOCKED_CLASSES = {
    "progman",              # Desktop
    "workerw",              # Desktop worker
    "cabinetwclass",        # File Explorer
    "shell_traywnd",        # Taskbar
    "shell_secondarytraywd",  # Secondary taskbar
    "taskmanagerwindow",    # Task Manager
    "applicationframewindow_notext",  # Placeholder UWP
}


def _get_class_name(hwnd: int) -> str:
    """Get the window class name for an HWND. Returns empty string on failure."""
    buf = ctypes.create_unicode_buffer(256)
    length = GetClassName(hwnd, buf, 256)
    return buf.value if length > 0 else ""


def _get_gui_thread_info(thread_id: int) -> GUITHREADINFO | None:
    """Get GUI thread info. Returns None on failure."""
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if GetGUIThreadInfo(thread_id, ctypes.byref(info)):
        return info
    return None


# --- Public API ---

def check_text_field() -> tuple[bool, str, int]:
    """Check if the currently focused control is a viable text field.

    Returns (is_viable, class_name, foreground_hwnd).
    - is_viable: True if recording should be allowed
    - class_name: the detected class name (for logging/whitelist building)
    - foreground_hwnd: the foreground window HWND
    """
    try:
        fg_hwnd = GetForegroundWindow()
        if not fg_hwnd:
            return False, "(no window)", 0

        fg_class = _get_class_name(fg_hwnd).lower()

        # Check blocked classes first
        if fg_class in _BLOCKED_CLASSES:
            log.info("Guard BLOCK: foreground class '%s' is blocked", fg_class)
            return False, fg_class, fg_hwnd

        # Get the focused child control via GUI thread info
        pid = ctypes.wintypes.DWORD()
        thread_id = GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid))
        info = _get_gui_thread_info(thread_id)

        # Determine which HWND to check: focused child or foreground window
        check_hwnd = fg_hwnd
        check_class = fg_class
        has_caret = False

        if info:
            if info.hwndFocus:
                check_hwnd = info.hwndFocus
                check_class = _get_class_name(check_hwnd).lower()
            has_caret = bool(info.hwndCaret)

        # Check known editable classes
        if check_class in _EDITABLE_CLASSES:
            log.info("Guard ALLOW: editable class '%s'", check_class)
            return True, check_class, fg_hwnd

        # Check browser/Electron renderers (permissive — assume editable)
        if check_class in _BROWSER_CLASSES or fg_class in _BROWSER_CLASSES:
            log.info("Guard ALLOW: browser class '%s' (permissive)", check_class)
            return True, check_class, fg_hwnd

        # Active caret means something is editable
        if has_caret:
            log.info("Guard ALLOW: active caret in '%s'", check_class)
            return True, check_class, fg_hwnd

        # Unknown class — permissive default (allow + log for whitelist building)
        log.info("Guard ALLOW: unknown class '%s' (permissive default)", check_class)
        return True, check_class, fg_hwnd

    except Exception:
        log.exception("Focus guard check failed — allowing recording")
        return True, "(error)", 0


def capture_target() -> int:
    """Capture and return the current foreground window HWND."""
    try:
        hwnd = GetForegroundWindow()
        class_name = _get_class_name(hwnd)
        log.info("Target captured: hwnd=%d, class='%s'", hwnd, class_name)
        return hwnd
    except Exception:
        log.exception("Failed to capture target window")
        return 0


def is_target_alive(hwnd: int) -> bool:
    """Check if a saved HWND is still a valid window."""
    if not hwnd:
        return False
    try:
        return bool(IsWindow(hwnd))
    except Exception:
        return False


def refocus_target(target_hwnd: int) -> bool:
    """Bring the target window to the foreground.

    Uses AttachThreadInput + SetForegroundWindow (standard accessibility technique).
    Returns True if refocus succeeded, False otherwise.
    """
    if not target_hwnd or not is_target_alive(target_hwnd):
        log.warning("Refocus skipped: target hwnd=%d is gone", target_hwnd)
        return False

    try:
        current_fg = GetForegroundWindow()
        if current_fg == target_hwnd:
            return True  # Already focused

        # Attach our thread to the foreground window's thread to gain SetForegroundWindow rights
        our_thread = GetCurrentThreadId()
        fg_pid = ctypes.wintypes.DWORD()
        fg_thread = GetWindowThreadProcessId(current_fg, ctypes.byref(fg_pid))

        attached = False
        if fg_thread != our_thread:
            attached = bool(AttachThreadInput(our_thread, fg_thread, True))

        result = bool(SetForegroundWindow(target_hwnd))

        if attached:
            AttachThreadInput(our_thread, fg_thread, False)

        if result:
            log.info("Refocused target hwnd=%d", target_hwnd)
        else:
            log.warning("SetForegroundWindow failed for hwnd=%d (may be elevated)", target_hwnd)

        return result

    except Exception:
        log.exception("Refocus failed for hwnd=%d", target_hwnd)
        return False
