"""Desktop shortcut creation via PowerShell WScript.Shell COM.

Creates a .lnk file on the user's desktop that launches the transcriber
via pythonw.exe (windowless) with a custom mic icon.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from autostart import resolve_pythonw

log = logging.getLogger("transcriber.shortcut")

_APP_DIR = Path(__file__).parent
_ICON_PATH = _APP_DIR / "icon.ico"
_SHORTCUT_NAME = "Transcriber.lnk"


def create_icon() -> Path:
    """Generate a mic .ico file from PIL (cached — only regenerated if missing)."""
    if _ICON_PATH.exists():
        return _ICON_PATH

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = "#4A90D9"
    draw.ellipse([16, 8, 48, 40], fill=color)
    draw.rectangle([28, 40, 36, 52], fill=color)
    draw.rectangle([20, 52, 44, 56], fill=color)
    img.save(str(_ICON_PATH), format="ICO")
    log.info("Generated icon at %s", _ICON_PATH)
    return _ICON_PATH


def create_desktop_shortcut() -> bool:
    """Create a desktop shortcut (.lnk) that launches the app windowless.

    Uses PowerShell + WScript.Shell COM (universal on Windows 10/11).
    Returns True on success, False on failure.
    """
    try:
        icon_path = create_icon()
        pythonw = resolve_pythonw()
        script = str(_APP_DIR / "app.py")

        # Use shell folder API — handles OneDrive-redirected desktops
        desktop = Path(subprocess.check_output(
            ["powershell", "-Command",
             "[Environment]::GetFolderPath('Desktop')"],
            text=True,
        ).strip())

        shortcut_path = desktop / _SHORTCUT_NAME

        # PowerShell script using WScript.Shell COM to create .lnk
        ps_script = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{shortcut_path}"); '
            f'$s.TargetPath = "{pythonw}"; '
            f'$s.Arguments = "{script}"; '
            f'$s.WorkingDirectory = "{_APP_DIR}"; '
            f'$s.IconLocation = "{icon_path},0"; '
            f'$s.Description = "Personal Transcriber — voice to text"; '
            f'$s.Save()'
        )

        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=10,
        )

        if result.returncode == 0:
            log.info("Desktop shortcut created: %s", shortcut_path)
            return True
        else:
            log.error("Shortcut creation failed: %s", result.stderr.strip())
            return False

    except Exception:
        log.exception("Desktop shortcut creation failed")
        return False
