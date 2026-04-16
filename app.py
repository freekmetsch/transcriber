"""
Personal Transcriber — Desktop voice-to-text with push-to-talk.
Entry point: system tray icon, global hotkey, recording/transcription pipeline.
"""

import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

import keyboard
import pystray
from PIL import Image, ImageDraw

import autostart
import focus_guard
import notifications
import shortcut
import sounds
from cascade_dictator import CascadeDictator
from cloud_dictator import CloudDictator
from config import load_config
from recorder import Recorder, StreamingRecorder
from transcriber import Transcriber
from postprocessor import build_cloud_system_prompt, ollama_health_check
from output import (output_text_to_target,
                    save_clipboard, restore_clipboard)
from recording_indicator import RecordingIndicator

# Logging: console + rotating file (works with both python.exe and pythonw.exe)
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_FILE = Path(__file__).parent / "transcriber.log"

logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
try:
    _file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    _file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logging.getLogger().addHandler(_file_handler)
except PermissionError:
    logging.warning("Cannot write to %s — file logging disabled", _LOG_FILE)

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
            on_level=self._on_audio_level,
        )
        self.transcriber = Transcriber(
            model_size=self.config["whisper"]["model_size"],
            device=self.config["whisper"]["device"],
            compute_type=self.config["whisper"]["compute_type"],
        )

        cc = self.config["whisper"]["cloud"]
        cloud = None
        if cc["enabled"] and cc["api_key"]:
            cloud = CloudDictator(
                api_key=cc["api_key"],
                model=cc["model"],
                base_url=cc["base_url"],
                referer=cc["referer"],
                title=cc["title"],
                timeout=cc["timeout"],
                failure_threshold=cc["failure_threshold"],
                cooldown_s=cc["cooldown_s"],
            )
            log.info(
                "cloud dictation: enabled (provider=%s model=%s)",
                cc["provider"], cc["model"],
            )
        elif cc["enabled"]:
            log.info("cloud dictation: enabled in config but api_key missing — using local only")
        else:
            log.info("cloud dictation: disabled (local only)")
        self.dictator = CascadeDictator(
            cloud=cloud,
            transcriber=self.transcriber,
            pp_config=self.config["postprocessing"],
            build_system_prompt=build_cloud_system_prompt,
        )

        self._recording = False
        self._lock = threading.Lock()
        self._icon: pystray.Icon | None = None
        self._last_toggle_time: float = 0.0
        self._target_hwnd: int = 0
        self._last_action_status: str = ""

        # Streaming recorder (created if streaming enabled)
        self._streaming_enabled = self.config["streaming"]["enabled"]
        if self._streaming_enabled:
            scfg = self.config["streaming"]
            self.streaming_recorder = StreamingRecorder(
                sample_rate=self.config["audio"]["sample_rate"],
                channels=self.config["audio"]["channels"],
                device=self.config["audio"].get("device"),
                silence_threshold=scfg["silence_threshold"],
                silence_duration_ms=scfg["silence_duration_ms"],
                min_segment_ms=scfg["min_segment_ms"],
                max_segment_s=scfg["max_segment_s"],
                on_level=self._on_audio_level,
            )
            log.info("Streaming mode enabled (threshold=%.3f, silence=%dms)",
                     scfg["silence_threshold"], scfg["silence_duration_ms"])

        # Streaming session state
        self._segment_context: str = ""
        self._clipboard_original: str | None = None

        # Brain (vocabulary database) — initialized if enabled
        self._brain = None
        self._correction_ui = None
        self._vocab_manager = None
        self._initial_prompt: str = ""
        self._vocabulary_text: str = ""
        self._last_transcription: str = ""

        # Recording indicator (Win+H-style overlay)
        self._recording_indicator = RecordingIndicator(on_stop=self._toggle_recording)
        self._recording_indicator.start()

        # Sound feedback
        sounds.set_enabled(self.config["ui"]["sounds"])

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

        # Build initial prompt for Whisper conditioning (use cache if available)
        self._initial_prompt = get_or_build_prompt(
            self._brain, max_chars=brain_cfg["prompt_max_chars"]
        )
        self._vocabulary_text = get_vocabulary_for_llm(self._brain)

        if self._initial_prompt:
            log.info("Whisper initial_prompt: %s", self._initial_prompt[:80] + "..." if len(self._initial_prompt) > 80 else self._initial_prompt)
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
            if notifications.is_available():
                log.info("Toast notifications enabled (brain)")
            else:
                log.info("Toast notifications unavailable (winotify not installed)")

    def _rebuild_prompts(self):
        """Rebuild Whisper initial_prompt and LLM vocabulary after brain mutations."""
        from prompt_builder import get_or_build_prompt, get_vocabulary_for_llm

        brain_cfg = self.config["brain"]
        self._initial_prompt = get_or_build_prompt(
            self._brain, max_chars=brain_cfg["prompt_max_chars"], force_rebuild=True
        )
        self._vocabulary_text = get_vocabulary_for_llm(self._brain)
        self._refresh_tray_menu()

    def _on_correction(self, original: str, corrected: str):
        """Callback from correction UI — log correction and check auto-learning."""
        if self._brain is None:
            return
        from learning import process_correction

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
                    notifications.notify_auto_learned(
                        entry["term"], entry["phonetic_hint"],
                        brain_cfg["auto_learn_threshold"],
                    )
            self._rebuild_prompts()

    def _on_vocab_add(self, term: str, hint: str | None, priority: str):
        """Callback from correction UI quick-add panel."""
        if self._brain is None:
            return
        self._brain.add_term(term, phonetic_hint=hint, priority=priority)
        log.info("Quick-added vocab: %s (hint=%s, priority=%s)", term, hint, priority)

        if self._notifications_enabled:
            notifications.notify_vocab_added(term)

        self._rebuild_prompts()

    def _on_vocab_change(self):
        """Callback from vocabulary manager — rebuild prompts and refresh tray."""
        if self._brain is None:
            return
        self._rebuild_prompts()
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
        """Build tray icon tooltip with hotkey hint, vocab count, and last action."""
        hotkey = self.config["hotkey"].replace("+", "+").title()
        base = f"Transcriber — {hotkey} to dictate"
        if self._brain is not None:
            base += f" ({self._brain.term_count()} terms)"
        if self._last_action_status:
            base += f"\n{self._last_action_status}"
        return base

    def _toggle_recording(self):
        # Debounce: keyboard library fires repeatedly while keys are held
        now = time.monotonic()
        if now - self._last_toggle_time < 0.5:
            return
        self._last_toggle_time = now

        with self._lock:
            if self._recording:
                self._recording = False
                sounds.play_stop()
                log.info("Recording stopped (toggle)")
                self._update_icon(False)
                if self._streaming_enabled:
                    threading.Thread(target=self._stop_streaming, daemon=True).start()
                else:
                    # Keep indicator visible during transcription — hide after output
                    self._recording_indicator.set_state("transcribing")
                    threading.Thread(target=self._stop_and_transcribe, daemon=True).start()
            else:
                # Text field guard: block recording if no text field detected
                is_viable, class_name, hwnd = focus_guard.check_text_field()
                if not is_viable:
                    log.info("Recording blocked: no text field (%s)", class_name)
                    sounds.play_error()
                    notifications.notify_guard_blocked(class_name)
                    self._last_action_status = f"Blocked: {class_name}"
                    self._update_icon(False)
                    return

                self._target_hwnd = hwnd
                self._recording = True
                sounds.play_start()
                log.info("Recording started — target: %s (hwnd=%d)", class_name, hwnd)
                self._update_icon(True)
                if self._streaming_enabled:
                    self._start_streaming()
                else:
                    self._recording_indicator.show()
                    self.recorder.start()

    # --- Streaming pipeline ---

    def _start_streaming(self):
        """Begin streaming recording with VAD."""
        self._segment_context = ""
        method = self.config["ui"]["output_method"]
        if method == "paste":
            self._clipboard_original = save_clipboard()
        else:
            self._clipboard_original = None
        self._recording_indicator.show()
        self.streaming_recorder.start(on_segment=self._on_speech_segment)

    def _on_audio_level(self, rms: float):
        """Forward mic RMS to the recording indicator's level bar. Thread-safe."""
        if self.config["ui"]["show_level_meter"]:
            self._recording_indicator.update_level(rms)

    def _on_speech_segment(self, audio):
        """Called per speech segment from the StreamingRecorder worker thread.

        Hot path: cascade dictation (cloud → local fallback) → output.
        Cloud path: OpenRouter audio-chat returns already-formatted text.
        Local path: Whisper + apply_formatting_commands.
        """
        self._recording_indicator.set_state("transcribing")
        t_start = time.monotonic()

        try:
            t_dictate = time.monotonic()
            result = self.dictator.dictate(
                audio,
                mode="streaming",
                vocabulary_text=self._vocabulary_text,
                previous_segment=self._segment_context,
                initial_prompt=self._segment_context or self._initial_prompt or None,
            )
            result = result.strip()
            t_dictate = time.monotonic() - t_dictate
        except Exception:
            log.exception("Segment dictation failed")
            sounds.play_error()
            self._recording_indicator.set_state("listening")
            return

        if not result:
            self._recording_indicator.set_state("listening")
            return

        t_total = time.monotonic() - t_start
        log.info(
            "Segment timing: dictate=%.2fs (%s), total=%.2fs",
            t_dictate, self.dictator.last_path, t_total,
        )

        if self._segment_context:
            result = " " + result

        output_method = self.config["ui"]["output_method"]
        output_text_to_target(result, self._target_hwnd,
                              method=output_method, streaming=True)

        self._segment_context = result.strip()
        self._last_transcription = result.strip()
        self._last_action_status = f"Dictated: {result.strip()[:40]}"
        self._recording_indicator.set_state("listening")
        if self.config["ui"]["show_language"]:
            self._recording_indicator.show_text(
                result.strip(),
                language=self.dictator.last_language,
                confidence=self.dictator.last_language_probability,
            )
        else:
            self._recording_indicator.show_text(result.strip())
        self._recording_indicator.show_feedback("success")
        log.info("Segment output: %s", result.strip())

    def _stop_streaming(self):
        """Stop streaming, flush remaining audio, restore clipboard."""
        remaining = self.streaming_recorder.stop()

        if remaining is not None and len(remaining) > 0:
            self._on_speech_segment(remaining)

        self._recording_indicator.hide()
        if self._clipboard_original is not None:
            restore_clipboard(self._clipboard_original)
            self._clipboard_original = None
            log.info("Streaming session ended, clipboard restored")
        else:
            log.info("Streaming session ended")

    # --- Batch pipeline ---

    def _stop_and_transcribe(self):
        audio = self.recorder.stop()
        if audio is None or len(audio) == 0:
            log.warning("No audio captured")
            sounds.play_error()
            self._recording_indicator.hide()
            return
        try:
            self._recording_indicator.set_state("processing")
            t_start = time.monotonic()
            t_dictate = time.monotonic()
            result = self.dictator.dictate(
                audio,
                mode="batch",
                vocabulary_text=self._vocabulary_text,
                previous_segment="",
                initial_prompt=self._initial_prompt or None,
            )
            result = result.strip()
            t_dictate = time.monotonic() - t_dictate
            t_total = time.monotonic() - t_start
            if result:
                log.info(
                    "Batch timing: dictate=%.2fs (%s), total=%.2fs",
                    t_dictate, self.dictator.last_path, t_total,
                )
                log.info("Output: %s", result)
                self._last_transcription = result
                self._last_action_status = f"Dictated: {result[:40]}"
                output_method = self.config["ui"]["output_method"]
                output_text_to_target(result, self._target_hwnd, method=output_method)

                self._recording_indicator.show_feedback("success")
                time.sleep(0.4)
                self._recording_indicator.hide()

                self._show_correction_auto(result)
            else:
                log.warning("Dictation returned empty text")
                sounds.play_error()
                self._recording_indicator.hide()
        except Exception:
            log.exception("Dictation failed")
            sounds.play_error()
            notifications.notify_error("Dictation failed", "Check microphone and try again")
            self._recording_indicator.hide()

    def _register_hotkey(self):
        hotkey = self.config["hotkey"]
        keyboard.add_hotkey(hotkey, self._toggle_recording, suppress=True)
        log.info("Hotkey registered: %s (toggle)", hotkey)

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
        import_path = Path(__file__).parent / "brain_export.json"
        if not import_path.exists():
            log.warning("No brain_export.json found at %s", import_path)
            return

        count_before = self._brain.term_count()
        self._brain.import_from_file(import_path)
        count_after = self._brain.term_count()
        imported = count_after - count_before

        self._rebuild_prompts()

        if self._notifications_enabled and imported > 0:
            notifications.notify_vocab_imported(imported, "brain_export.json")

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

        menu_items.extend([
            pystray.MenuItem(
                "Create Desktop Shortcut",
                self._create_shortcut,
            ),
            pystray.MenuItem(
                lambda item: "Start with Windows  \u2713" if autostart.is_enabled()
                             else "Start with Windows",
                lambda icon, item: autostart.toggle(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        ])
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

    def _create_shortcut(self, icon=None, item=None):
        """Create a desktop shortcut from tray menu."""
        success = shortcut.create_desktop_shortcut()
        if success:
            notifications.notify_info("Desktop shortcut created", "Launch Transcriber from your desktop")
        else:
            notifications.notify_error("Shortcut failed", "Check log for details")

    def _quit(self, icon, item):
        log.info("Shutting down")
        keyboard.unhook_all()
        self._recording_indicator.destroy()
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
            primary_ok = ollama_health_check(pp["base_url"])
            fallback_url = pp.get("fallback_url")
            fallback_ok = ollama_health_check(fallback_url) if fallback_url else None

            if primary_ok:
                log.info("Ollama primary: %s \u2713 (model: %s)", pp["base_url"], pp["model"])
            else:
                log.warning("Ollama primary: %s \u2717", pp["base_url"])

            if fallback_url is not None:
                if fallback_ok:
                    log.info("Ollama fallback: %s \u2713", fallback_url)
                else:
                    log.warning("Ollama fallback: %s \u2717", fallback_url)

            if not primary_ok and (fallback_url is None or not fallback_ok):
                log.warning("Ollama: no endpoints reachable — post-processing will use raw text")
            elif not primary_ok and fallback_ok:
                log.info("Primary unavailable — will use fallback for post-processing")

        self._register_hotkey()

        menu = self._build_tray_menu()
        self._icon = pystray.Icon(
            "transcriber", _ICON_IDLE, self._tray_tooltip(), menu
        )

        brain_status = ""
        if self._brain is not None:
            brain_status = f" Brain: {self._brain.term_count()} terms."
        log.info(
            "Transcriber ready. Press %s to start/stop dictation.%s",
            self.config["hotkey"], brain_status,
        )

        # Startup toast
        notifications.notify_startup(self.config["hotkey"])

        try:
            self._icon.run()
        finally:
            keyboard.unhook_all()
            if self._brain:
                self._brain.close()


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
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
