"""Windows auto-start via Registry Run key.

Adds/removes an entry in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
that launches the transcriber on login using pythonw.exe (windowless).
"""

import logging
import os
import sys
import winreg

log = logging.getLogger("transcriber.autostart")

_APP_NAME = "Transcriber"
_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_launch_command() -> str:
    """Build the command string for auto-start using absolute paths."""
    python = sys.executable
    # Prefer pythonw.exe for windowless launch
    if python.endswith("python.exe"):
        pythonw = python.replace("python.exe", "pythonw.exe")
        if os.path.exists(pythonw):
            python = pythonw
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "app.py"))
    return f'"{python}" "{script}"'


def is_enabled() -> bool:
    """Check if auto-start is currently registered."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except FileNotFoundError:
        return False


def enable():
    """Register auto-start in the Windows registry."""
    cmd = _get_launch_command()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH,
                        0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, cmd)
    log.info("Auto-start enabled: %s", cmd)


def disable():
    """Remove auto-start from the Windows registry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _APP_NAME)
        log.info("Auto-start disabled")
    except FileNotFoundError:
        log.debug("Auto-start was not enabled")


def toggle() -> bool:
    """Toggle auto-start. Returns the new state (True = enabled)."""
    if is_enabled():
        disable()
        return False
    else:
        enable()
        return True
