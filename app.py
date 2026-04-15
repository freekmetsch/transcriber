"""
Personal Transcriber — Desktop voice-to-text with push-to-talk.
Entry point: system tray icon, global hotkey, recording/transcription pipeline.
"""

import logging
import sys
import threading

import keyboard
import pystray
from PIL import Image, ImageDraw

from config import load_config
from recorder import Recorder
from transcriber import Transcriber
from postprocessor import postprocess_text, ollama_health_check
from output import paste_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("transcriber")


def _build_icon_image(recording: bool = False) -> Image.Image:
    """Create a simple mic icon — blue when idle, red when recording."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = "#E74C3C" if recording else "#4A90D9"
    draw.ellipse([16, 8, 48, 40], fill=color)
    draw.rectangle([28, 40, 36, 52], fill=color)
    draw.rectangle([20, 52, 44, 56], fill=color)
    return image


# Pre-build both icon states once at import time
_ICON_IDLE = _build_icon_image(False)
_ICON_RECORDING = _build_icon_image(True)


class TranscriberApp:
    def __init__(self):
        self.config = load_config()
        self.recorder = Recorder(
            sample_rate=self.config["audio"]["sample_rate"],
            channels=self.config["audio"]["channels"],
            device=self.config["audio"].get("device"),
        )
        self.transcriber = Transcriber(
            model_size=self.config["whisper"]["model_size"],
            device=self.config["whisper"]["device"],
            compute_type=self.config["whisper"]["compute_type"],
        )
        self._recording = False
        self._lock = threading.Lock()
        self._icon: pystray.Icon | None = None
        # Parse the trigger key (last key in the hotkey combo) for the release handler
        self._trigger_key = self.config["hotkey"].split("+")[-1].strip()

    def _update_icon(self, recording: bool):
        if self._icon is not None:
            self._icon.icon = _ICON_RECORDING if recording else _ICON_IDLE
            self._icon.title = (
                "Transcriber — Recording..." if recording else "Transcriber"
            )

    def _start_recording(self):
        with self._lock:
            if self._recording:
                return
            self._recording = True
        log.info("Recording started (push-to-talk)")
        self._update_icon(True)
        self.recorder.start()

    def _on_trigger_release(self, event):
        with self._lock:
            if not self._recording:
                return
            self._recording = False
        log.info("Recording stopped")
        self._update_icon(False)
        # Move stop + transcribe off the keyboard hook thread
        threading.Thread(target=self._stop_and_transcribe, daemon=True).start()

    def _stop_and_transcribe(self):
        audio = self.recorder.stop()
        if audio is None or len(audio) == 0:
            log.warning("No audio captured")
            return
        try:
            text = self.transcriber.transcribe(audio)
            text = text.strip()
            if text:
                log.info("Raw transcription: %s", text)
                text = postprocess_text(text, self.config["postprocessing"])
                log.info("Output: %s", text)
                paste_text(text)
            else:
                log.warning("Transcription returned empty text")
        except Exception:
            log.exception("Transcription failed")

    def _register_hotkey(self):
        hotkey = self.config["hotkey"]
        keyboard.add_hotkey(hotkey, self._start_recording, suppress=True)
        keyboard.on_release_key(self._trigger_key, self._on_trigger_release)
        log.info("Hotkey registered: %s (push-to-talk)", hotkey)

    def _quit(self, icon, item):
        log.info("Shutting down")
        keyboard.unhook_all()
        icon.stop()

    def run(self):
        log.info("Starting Transcriber")
        log.info(
            "Loading Whisper model '%s' on %s...",
            self.config["whisper"]["model_size"],
            self.config["whisper"]["device"],
        )
        self.transcriber.load_model()
        log.info("Model loaded")

        pp = self.config["postprocessing"]
        if pp["enabled"]:
            if ollama_health_check(pp["base_url"]):
                log.info("Ollama reachable at %s (model: %s)", pp["base_url"], pp["model"])
            else:
                log.warning("Ollama not reachable at %s — post-processing will fall back to raw text", pp["base_url"])

        self._register_hotkey()

        menu = pystray.Menu(
            pystray.MenuItem("Transcriber", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self._icon = pystray.Icon(
            "transcriber", _ICON_IDLE, "Transcriber", menu
        )
        log.info("Transcriber ready. Hold %s to dictate.", self.config["hotkey"])
        try:
            self._icon.run()
        finally:
            keyboard.unhook_all()


def main():
    try:
        app = TranscriberApp()
        app.run()
    except KeyboardInterrupt:
        log.info("Interrupted")
    except Exception:
        log.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
