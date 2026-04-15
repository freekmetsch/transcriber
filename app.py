"""
Personal Transcriber — Desktop voice-to-text with push-to-talk.
Entry point: system tray icon, global hotkey, recording/transcription pipeline.
"""

import logging
import sys
import threading
from pathlib import Path

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
        self._trigger_key = self.config["hotkey"].split("+")[-1].strip()

        # Brain (vocabulary database) — initialized if enabled
        self._brain = None
        self._correction_ui = None
        self._vocab_manager = None
        self._initial_prompt: str = ""
        self._vocabulary_text: str = ""
        self._last_transcription: str = ""

        # Notifications
        self._notifications_enabled = False

        brain_cfg = self.config["brain"]
        if brain_cfg["enabled"]:
            self._init_brain(brain_cfg)

    def _init_brain(self, brain_cfg: dict):
        """Initialize the vocabulary brain, correction UI, vocab manager, and notifications."""
        from brain import VocabularyBrain
        from prompt_builder import get_or_build_prompt, get_vocabulary_for_llm
        from correction_ui import CorrectionWindow

        db_path = Path(__file__).parent / brain_cfg["db_path"]
        self._brain = VocabularyBrain(db_path)

        # Build initial prompt for Whisper conditioning
        self._initial_prompt = get_or_build_prompt(
            self._brain, max_chars=brain_cfg["prompt_max_chars"]
        )
        if self._initial_prompt:
            log.info("Whisper initial_prompt: %s", self._initial_prompt[:80] + "..." if len(self._initial_prompt) > 80 else self._initial_prompt)

        # Build vocabulary text for LLM post-processing
        self._vocabulary_text = get_vocabulary_for_llm(self._brain)
        if self._vocabulary_text:
            log.info("Loaded %d vocabulary terms for post-processing", self._vocabulary_text.count("\n") + 1)

        # Correction UI
        self._correction_ui = CorrectionWindow(
            on_correction=self._on_correction,
            on_vocab_add=self._on_vocab_add,
        )
        self._correction_ui.start()
        log.info("Correction UI ready (mode: %s)", brain_cfg["correction_mode"])

        # Vocabulary manager (uses the same Tk root)
        if self._correction_ui._root:
            from vocab_ui import VocabularyManager
            self._vocab_manager = VocabularyManager(
                self._correction_ui._root,
                self._brain,
                on_change=self._on_vocab_change,
            )
            log.info("Vocabulary manager ready")

        # Notifications
        self._notifications_enabled = brain_cfg.get("notifications", True)
        if self._notifications_enabled:
            import notifications
            if notifications.is_available():
                log.info("Toast notifications enabled")
            else:
                log.info("Toast notifications unavailable (winotify not installed)")

    def _on_correction(self, original: str, corrected: str):
        """Callback from correction UI — log correction and check auto-learning."""
        if self._brain is None:
            return
        from learning import process_correction
        from prompt_builder import get_or_build_prompt, get_vocabulary_for_llm

        brain_cfg = self.config["brain"]
        learned = process_correction(
            self._brain,
            original,
            corrected,
            auto_learn_threshold=brain_cfg["auto_learn_threshold"],
        )
        if learned:
            for entry in learned:
                log.info("Auto-learned term: %s (was: %s)", entry["term"], entry["phonetic_hint"])
                if self._notifications_enabled:
                    import notifications
                    notifications.notify_auto_learned(
                        entry["term"], entry["phonetic_hint"],
                        brain_cfg["auto_learn_threshold"],
                    )
            # Rebuild prompts since vocabulary changed
            self._initial_prompt = get_or_build_prompt(
                self._brain,
                max_chars=brain_cfg["prompt_max_chars"],
                force_rebuild=True,
            )
            self._vocabulary_text = get_vocabulary_for_llm(self._brain)
            self._refresh_tray_menu()

    def _on_vocab_add(self, term: str, hint: str | None, priority: str):
        """Callback from correction UI quick-add panel."""
        if self._brain is None:
            return
        from prompt_builder import get_or_build_prompt, get_vocabulary_for_llm

        self._brain.add_term(term, phonetic_hint=hint, priority=priority)
        log.info("Quick-added vocab: %s (hint=%s, priority=%s)", term, hint, priority)

        if self._notifications_enabled:
            import notifications
            notifications.notify_vocab_added(term)

        # Rebuild prompts
        brain_cfg = self.config["brain"]
        self._initial_prompt = get_or_build_prompt(
            self._brain, max_chars=brain_cfg["prompt_max_chars"], force_rebuild=True
        )
        self._vocabulary_text = get_vocabulary_for_llm(self._brain)
        self._refresh_tray_menu()

    def _on_vocab_change(self):
        """Callback from vocabulary manager — rebuild prompts and refresh tray."""
        if self._brain is None:
            return
        from prompt_builder import get_or_build_prompt, get_vocabulary_for_llm

        brain_cfg = self.config["brain"]
        self._initial_prompt = get_or_build_prompt(
            self._brain, max_chars=brain_cfg["prompt_max_chars"], force_rebuild=True
        )
        self._vocabulary_text = get_vocabulary_for_llm(self._brain)
        self._refresh_tray_menu()
        log.info("Vocabulary changed — prompts rebuilt, tray refreshed")

    def _open_correction_window(self):
        """Open the correction window with the last transcription."""
        if self._correction_ui and self._last_transcription:
            self._correction_ui.show(self._last_transcription)
        elif not self._last_transcription:
            log.debug("No transcription to correct")

    def _show_correction_auto(self, text: str):
        """Auto-show the correction window after transcription (non-focused)."""
        if self._correction_ui is None:
            return
        brain_cfg = self.config["brain"]
        mode = brain_cfg.get("correction_mode", "auto")
        if mode == "auto":
            timeout = brain_cfg.get("correction_timeout", 8)
            self._correction_ui.show_passive(text, timeout=timeout)
        # In "hotkey" or "off" mode, don't auto-show

    def _open_vocab_manager(self, icon=None, item=None):
        """Open the vocabulary manager window from tray menu."""
        if self._vocab_manager:
            self._vocab_manager.schedule_show()

    def _update_icon(self, recording: bool):
        if self._icon is not None:
            self._icon.icon = _ICON_RECORDING if recording else _ICON_IDLE
            self._icon.title = (
                "Transcriber — Recording..." if recording else self._tray_tooltip()
            )

    def _tray_tooltip(self) -> str:
        """Build tray icon tooltip with vocabulary count."""
        if self._brain is not None:
            return f"Transcriber — {self._brain.term_count()} terms"
        return "Transcriber"

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
        threading.Thread(target=self._stop_and_transcribe, daemon=True).start()

    def _stop_and_transcribe(self):
        audio = self.recorder.stop()
        if audio is None or len(audio) == 0:
            log.warning("No audio captured")
            return
        try:
            text = self.transcriber.transcribe(
                audio,
                initial_prompt=self._initial_prompt or None,
            )
            text = text.strip()
            if text:
                log.info("Raw transcription: %s", text)
                result = postprocess_text(
                    text,
                    self.config["postprocessing"],
                    vocabulary_text=self._vocabulary_text,
                )
                # Check if postprocessing fell back to raw text
                if result == text and self.config["postprocessing"]["enabled"]:
                    if self._notifications_enabled:
                        import notifications
                        notifications.notify_ollama_fallback()

                log.info("Output: %s", result)
                self._last_transcription = result
                paste_text(result)

                # Auto-show correction window if configured
                self._show_correction_auto(result)
            else:
                log.warning("Transcription returned empty text")
        except Exception:
            log.exception("Transcription failed")

    def _register_hotkey(self):
        hotkey = self.config["hotkey"]
        keyboard.add_hotkey(hotkey, self._start_recording, suppress=True)
        keyboard.on_release_key(self._trigger_key, self._on_trigger_release)
        log.info("Hotkey registered: %s (push-to-talk)", hotkey)

        # Register correction hotkey if brain is enabled and mode is not "off"
        if self._brain is not None:
            brain_cfg = self.config["brain"]
            mode = brain_cfg.get("correction_mode", "auto")
            if mode != "off":
                corr_hotkey = brain_cfg["correction_hotkey"]
                keyboard.add_hotkey(corr_hotkey, self._open_correction_window, suppress=True)
                log.info("Correction hotkey registered: %s", corr_hotkey)

    def _export_vocabulary(self, icon, item):
        """Export vocabulary to JSON file."""
        if self._brain is None:
            return
        export_path = Path(__file__).parent / "brain_export.json"
        self._brain.export_to_file(export_path)
        log.info("Vocabulary exported to %s", export_path)

    def _import_vocabulary(self, icon, item):
        """Import vocabulary from JSON file."""
        if self._brain is None:
            return
        from prompt_builder import get_or_build_prompt, get_vocabulary_for_llm

        import_path = Path(__file__).parent / "brain_export.json"
        if not import_path.exists():
            log.warning("No brain_export.json found at %s", import_path)
            return

        count_before = self._brain.term_count()
        self._brain.import_from_file(import_path)
        count_after = self._brain.term_count()
        imported = count_after - count_before

        # Rebuild prompts
        brain_cfg = self.config["brain"]
        self._initial_prompt = get_or_build_prompt(
            self._brain, max_chars=brain_cfg["prompt_max_chars"], force_rebuild=True
        )
        self._vocabulary_text = get_vocabulary_for_llm(self._brain)

        if self._notifications_enabled and imported > 0:
            import notifications
            notifications.notify_vocab_imported(imported, "brain_export.json")

        self._refresh_tray_menu()
        log.info("Vocabulary imported and prompts rebuilt")

    def _build_tray_menu(self) -> pystray.Menu:
        """Build the tray menu with current vocabulary count."""
        menu_items = [
            pystray.MenuItem("Transcriber", None, enabled=False),
            pystray.Menu.SEPARATOR,
        ]

        if self._brain is not None:
            brain_cfg = self.config["brain"]
            mode = brain_cfg.get("correction_mode", "auto")
            menu_items.extend([
                pystray.MenuItem(
                    lambda item: f"Vocabulary ({self._brain.term_count()} terms)",
                    None, enabled=False,
                ),
                pystray.MenuItem(
                    "Manage vocabulary...",
                    self._open_vocab_manager,
                ),
            ])
            if mode != "off":
                menu_items.append(
                    pystray.MenuItem(
                        f"Correct last (  {brain_cfg['correction_hotkey']}  )",
                        lambda icon, item: self._open_correction_window(),
                    ),
                )
            menu_items.extend([
                pystray.MenuItem("Export vocabulary", self._export_vocabulary),
                pystray.MenuItem("Import vocabulary", self._import_vocabulary),
                pystray.Menu.SEPARATOR,
            ])

        menu_items.append(pystray.MenuItem("Quit", self._quit))
        return pystray.Menu(*menu_items)

    def _refresh_tray_menu(self):
        """Refresh the tray menu to update vocabulary count."""
        if self._icon is not None:
            self._icon.menu = self._build_tray_menu()
            self._icon.title = self._tray_tooltip()
            try:
                self._icon.update_menu()
            except Exception:
                # pystray backend may not support update_menu — tooltip still updates
                log.debug("Tray menu update not supported, tooltip updated instead")

    def _quit(self, icon, item):
        log.info("Shutting down")
        keyboard.unhook_all()
        if self._correction_ui:
            self._correction_ui.destroy()
        if self._brain:
            self._brain.close()
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

        menu = self._build_tray_menu()
        self._icon = pystray.Icon(
            "transcriber", _ICON_IDLE, self._tray_tooltip(), menu
        )

        brain_status = ""
        if self._brain is not None:
            brain_status = f" Brain: {self._brain.term_count()} terms."
        log.info(
            "Transcriber ready. Hold %s to dictate.%s",
            self.config["hotkey"], brain_status,
        )
        try:
            self._icon.run()
        finally:
            keyboard.unhook_all()
            if self._brain:
                self._brain.close()


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
