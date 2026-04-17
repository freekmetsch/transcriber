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
from collections import deque
from dataclasses import dataclass
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
from cloud_dictator import OpenRouterDictator
from commands import detect_control_command
from config import load_config
from modes import ModeManager, load_modes
from recorder import Recorder, StreamingRecorder
from transcriber import Transcriber
from postprocessor import build_cloud_system_prompt, ollama_health_check
from output import (output_text_to_target,
                    save_clipboard, restore_clipboard)
# RecordingIndicator is imported dynamically below based on ui.overlay_backend.

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


@dataclass
class HistoryEntry:
    text: str
    language: str
    timestamp: float


_TRAY_STATE_COLORS = {
    "idle":         "#4A90D9",  # Blue
    "listening":    "#E74C3C",  # Red
    "transcribing": "#F39C12",  # Orange
    "blocked":      "#777777",  # Grey
}

# Per-state tooltip titles. idle=None → use composed _tray_tooltip().
_TRAY_STATE_TITLES = {
    "idle":         None,
    "listening":    "Transcriber — Recording...",
    "transcribing": "Transcriber — Transcribing...",
    "blocked":      "Transcriber — No text field detected",
}


def _build_icon_image(state: str = "idle") -> Image.Image:
    """Create a mic icon colored per state. Blocked state overlays a red X."""
    color = _TRAY_STATE_COLORS.get(state, _TRAY_STATE_COLORS["idle"])
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([16, 8, 48, 40], fill=color)
    draw.rectangle([28, 40, 36, 52], fill=color)
    draw.rectangle([20, 52, 44, 56], fill=color)
    if state == "blocked":
        draw.line([14, 14, 50, 50], fill="#FF4444", width=6)
        draw.line([50, 14, 14, 50], fill="#FF4444", width=6)
    return image


# Pre-build all tray icon states once at import time
_ICON_STATES = {state: _build_icon_image(state) for state in _TRAY_STATE_COLORS}


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
            provider = cc["provider"]
            if provider == "groq":
                from groq_dictator import GroqDictator
                cloud = GroqDictator(
                    api_key=cc["api_key"],
                    stt_model=cc["stt_model"],
                    polish_model=cc["polish_model"],
                    base_url=cc["groq_base_url"],
                    stt_timeout=cc["stt_timeout"],
                    polish_timeout=cc["polish_timeout"],
                    failure_threshold=cc["failure_threshold"],
                    cooldown_s=cc["cooldown_s"],
                )
                log.info(
                    "cloud dictation: enabled (provider=groq stt=%s polish=%s)",
                    cc["stt_model"], cc["polish_model"],
                )
            elif provider == "openrouter":
                cloud = OpenRouterDictator(
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
                    "cloud dictation: enabled (provider=openrouter model=%s)",
                    cc["model"],
                )
            else:
                log.error(
                    "cloud dictation: unknown provider %r — disabling cloud", provider,
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
        self._last_output_length: int = 0

        # Dictation modes (switchable polish profiles)
        self._modes = ModeManager(
            modes=load_modes(self.config.get("modes")),
            state_path=Path(__file__).parent / "mode_state.json",
        )
        log.info(
            "Modes: %s (current: %s)",
            self._modes.names(), self._modes.current().name,
        )

        # Streaming recorder (created if streaming enabled)
        self._streaming_enabled = self.config["streaming"]["enabled"]
        if self._streaming_enabled:
            scfg = self.config["streaming"]
            vcfg = dict(scfg.get("vad") or {})
            # Energy engine reuses the legacy top-level streaming keys as its
            # tunables, so old config.local.yaml files still behave.
            if (vcfg.get("engine") or "silero").lower() == "energy":
                vcfg.setdefault("threshold", scfg.get("silence_threshold", 0.01))
                vcfg.setdefault("min_silence_ms", scfg.get("silence_duration_ms", 600))
            from vad import make_vad
            vad = make_vad(vcfg)
            self.streaming_recorder = StreamingRecorder(
                vad=vad,
                channels=self.config["audio"]["channels"],
                device=self.config["audio"].get("device"),
                target_sample_rate=self.config["audio"]["sample_rate"],
                preroll_ms=int(vcfg.get("preroll_ms", 300)),
                min_segment_ms=scfg["min_segment_ms"],
                max_segment_s=scfg["max_segment_s"],
                on_level=self._on_audio_level,
            )
            log.info("Streaming mode enabled (vad=%s)", type(vad).__name__)

        # Streaming session state
        self._segment_context: str = ""
        self._clipboard_original: str | None = None

        # Brain (vocabulary database) — initialized if enabled
        self._brain = None
        self._correction_ui = None
        self._vocab_manager = None
        self._initial_prompt: str = ""
        self._vocabulary_text: str = ""
        self._history: deque[HistoryEntry] = deque(
            maxlen=int(self.config["ui"].get("history_length", 10)),
        )
        self._show_history_on_hover: bool = bool(
            self.config["ui"].get("show_history_on_hover", False),
        )

        # Always-visible overlay (Win+H-style)
        self._overlay_close_toast_shown = False
        backend = (self.config["ui"].get("overlay_backend") or "qt").lower()
        if backend == "qt":
            from recording_indicator_qt import RecordingIndicator
        else:
            if backend != "tk":
                log.warning("Unknown ui.overlay_backend=%r; falling back to tk", backend)
            from recording_indicator_tk import RecordingIndicator
        self._recording_indicator = RecordingIndicator(
            on_mic_click=self._toggle_recording,
            on_dismiss=self._on_overlay_dismiss,
            get_menu_items=self._build_overlay_menu_items,
            visible_on_start=self.config["ui"].get("overlay_visible_on_start", True),
            get_mode_name=lambda: self._modes.current().name,
            on_mode_click=self._cycle_mode,
            get_history_entries=self._get_history_for_hover,
            get_history_hover_enabled=lambda: self._show_history_on_hover,
            on_history_repaste=self._on_history_repaste,
            on_history_discard=self._on_history_discard,
        )
        self._recording_indicator.start()

        # Sound feedback
        sounds.set_enabled(self.config["ui"]["sounds"])

        # Notifications
        self._notifications_enabled = False

        brain_cfg = self.config["brain"]
        if brain_cfg["enabled"]:
            self._init_brain(brain_cfg)

    @property
    def _last_transcription(self) -> str:
        return self._history[-1].text if self._history else ""

    def _append_history(self, text: str, language: str | None = ""):
        self._history.append(
            HistoryEntry(text=text, language=language or "", timestamp=time.time()),
        )

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

    def _set_tray_state(self, state: str):
        """Update tray icon glyph + tooltip for a given state.

        State values: idle | listening | transcribing | blocked.
        """
        if self._icon is None:
            return
        self._icon.icon = _ICON_STATES.get(state, _ICON_STATES["idle"])
        title = _TRAY_STATE_TITLES.get(state)
        self._icon.title = title if title is not None else self._tray_tooltip()

    def _set_state(self, state: str):
        """Sync overlay + tray to the same state (idle | listening | transcribing)."""
        self._recording_indicator.set_state(state)
        self._set_tray_state(state)

    def _return_to_idle(self):
        """End the overlay session and reset the tray to idle."""
        self._recording_indicator.end_session()
        self._set_tray_state("idle")

    def _tray_tooltip(self) -> str:
        """Build tray icon tooltip with hotkey hint, vocab count, and last action."""
        hotkey = self.config["hotkey"].replace("+", "+").title()
        base = f"Transcriber — {hotkey} to dictate"
        if self._brain is not None:
            base += f" ({self._brain.term_count()} terms)"
        if self._last_action_status:
            base += f"\n{self._last_action_status}"
        return base

    def _on_overlay_dismiss(self):
        """Called when user clicks X on the overlay. Shows a hint toast once per session."""
        if not self._overlay_close_toast_shown:
            self._overlay_close_toast_shown = True
            toggle_hk = self.config["ui"].get("toggle_overlay_hotkey", "ctrl+shift+h")
            notifications.notify_info(
                "Overlay hidden",
                f"Press {toggle_hk} or use the tray menu to show it again",
            )

    def _cycle_mode(self, icon=None, item=None):
        """Advance to the next dictation mode, persist, and notify."""
        new_mode = self._modes.cycle()
        log.info("Mode cycled: %s", new_mode.name)
        self._recording_indicator.refresh_mode()
        notifications.notify_info("Mode", f"Switched to {new_mode.name}")

    def _dispatch_control_command(self, command: str):
        """Handle a full-segment voice control command from _on_speech_segment."""
        if command == "stop":
            log.info("Voice command: stop listening")
            self._toggle_recording()
            return
        if command == "delete":
            n = self._last_output_length
            if n > 0:
                for _ in range(n):
                    keyboard.send("backspace")
                log.info("Voice command: delete (backspaced %d chars)", n)
            else:
                log.debug("Voice command: delete — nothing to undo")
            self._segment_context = ""
            if self._history:
                self._history.pop()
            self._last_output_length = 0
            if self._recording:
                self._set_state("listening")

    def _build_overlay_menu_items(self) -> list:
        """Build the overlay gear menu (mirrors tray menu, minus shortcut duplication)."""
        cycle_hk = self.config["ui"].get("cycle_mode_hotkey", "ctrl+shift+m")
        cycle_label = f"Cycle mode \u2192 {self._modes.current().name}"
        if cycle_hk:
            cycle_label += f"  ({cycle_hk})"
        hover_label = ("Show history on hover  \u2713" if self._show_history_on_hover
                       else "Show history on hover")
        items: list = [
            ("Hide overlay", self._recording_indicator.dismiss),
            (cycle_label, self._cycle_mode),
            (hover_label, self._toggle_history_on_hover),
            None,
        ]
        if self._brain is not None:
            items.extend([
                ("Manage vocabulary", self._open_vocab_manager),
                ("Export vocabulary", self._export_vocabulary),
                ("Import vocabulary", self._import_vocabulary),
                None,
            ])
        autostart_label = ("Start with Windows  \u2713" if autostart.is_enabled()
                           else "Start with Windows")
        items.extend([
            (autostart_label, autostart.toggle),
            None,
            ("Quit", self._quit),
        ])
        return items

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
                self._set_tray_state("transcribing")
                if self._streaming_enabled:
                    threading.Thread(target=self._stop_streaming, daemon=True).start()
                else:
                    # Keep indicator visible during transcription — returns to idle after output
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
                    self._set_tray_state("blocked")
                    return

                self._target_hwnd = hwnd
                self._recording = True
                sounds.play_start()
                log.info("Recording started — target: %s (hwnd=%d)", class_name, hwnd)
                self._set_tray_state("listening")
                if self._streaming_enabled:
                    self._start_streaming()
                else:
                    self._recording_indicator.begin_session()
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
        self._recording_indicator.begin_session()
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
        if not self._recording:
            # Session was cancelled while this segment was in flight — drop it.
            return
        self._set_state("transcribing")
        t_start = time.monotonic()

        try:
            t_dictate = time.monotonic()
            result = self.dictator.dictate(
                audio,
                mode="streaming",
                vocabulary_text=self._vocabulary_text,
                previous_segment=self._segment_context,
                initial_prompt=self._segment_context or self._initial_prompt or None,
                user_mode=self._modes.current(),
            )
            result = result.strip()
            t_dictate = time.monotonic() - t_dictate
        except Exception:
            log.exception("Segment dictation failed")
            sounds.play_error()
            self._set_state("listening")
            return

        if not result:
            self._set_state("listening")
            return

        # Full-segment voice control command takes priority over paste.
        command = detect_control_command(result)
        if command is not None:
            self._dispatch_control_command(command)
            return

        t_total = time.monotonic() - t_start
        log.info(
            "Segment timing: dictate=%.2fs (%s), total=%.2fs",
            t_dictate, self.dictator.last_path, t_total,
        )

        if not self._recording:
            # Cancelled while we were transcribing — don't paste.
            return

        if self._segment_context:
            result = " " + result

        output_method = self.config["ui"]["output_method"]
        output_text_to_target(result, self._target_hwnd,
                              method=output_method, streaming=True)

        self._last_output_length = len(result)
        self._segment_context = result.strip()
        self._append_history(result.strip(), language=self.dictator.last_language)
        self._last_action_status = f"Dictated: {result.strip()[:40]}"
        self._set_state("listening")
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

        self._return_to_idle()
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
            self._recording_indicator.end_session()
            self._set_tray_state("idle")
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
                user_mode=self._modes.current(),
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
                self._append_history(result, language=self.dictator.last_language)
                self._last_action_status = f"Dictated: {result[:40]}"
                output_method = self.config["ui"]["output_method"]
                output_text_to_target(result, self._target_hwnd, method=output_method)
                self._last_output_length = len(result)

                self._recording_indicator.show_feedback("success")
                time.sleep(0.4)
                self._recording_indicator.end_session()
                self._set_tray_state("idle")

                self._show_correction_auto(result)
            else:
                log.warning("Dictation returned empty text")
                sounds.play_error()
                self._recording_indicator.end_session()
                self._set_tray_state("idle")
        except Exception:
            log.exception("Dictation failed")
            sounds.play_error()
            notifications.notify_error("Dictation failed", "Check microphone and try again")
            self._recording_indicator.end_session()
            self._set_tray_state("idle")

    def _register_hotkey(self):
        hotkey = self.config["hotkey"]
        keyboard.add_hotkey(hotkey, self._toggle_recording, suppress=True)
        log.info("Hotkey registered: %s (toggle)", hotkey)

        # Overlay show/hide toggle (Ctrl+Shift+H by default)
        toggle_hk = self.config["ui"].get("toggle_overlay_hotkey", "ctrl+shift+h")
        if toggle_hk:
            try:
                keyboard.add_hotkey(
                    toggle_hk, self._recording_indicator.toggle_visibility, suppress=True,
                )
                log.info("Overlay toggle hotkey registered: %s", toggle_hk)
            except Exception:
                log.exception("Failed to register overlay toggle hotkey %s", toggle_hk)

        # Mode cycle hotkey (Ctrl+Shift+M by default)
        cycle_hk = self.config["ui"].get("cycle_mode_hotkey", "ctrl+shift+m")
        if cycle_hk:
            try:
                keyboard.add_hotkey(cycle_hk, self._cycle_mode, suppress=True)
                log.info("Mode cycle hotkey registered: %s", cycle_hk)
            except Exception:
                log.exception("Failed to register mode cycle hotkey %s", cycle_hk)

        # Re-paste last transcription hotkey (Ctrl+Alt+V by default; avoids the
        # browser/Office "paste plain text" collision on Ctrl+Shift+V).
        repaste_hk = self.config["ui"].get("repaste_hotkey", "ctrl+alt+v")
        if repaste_hk:
            try:
                keyboard.add_hotkey(repaste_hk, self._repaste_last, suppress=True)
                log.info("Re-paste hotkey registered: %s", repaste_hk)
            except Exception:
                log.exception("Failed to register re-paste hotkey %s", repaste_hk)

        # Esc cancels recording in-flight — suppress=False so Esc also reaches target apps
        try:
            keyboard.add_hotkey("esc", self._on_esc, suppress=False)
            log.info("Cancel hotkey registered: esc (observes only, does not suppress)")
        except Exception:
            log.exception("Failed to register Esc cancel hotkey")

        # Register correction hotkey if brain is enabled and mode is not "off"
        if self._brain is not None:
            brain_cfg = self.config["brain"]
            mode = brain_cfg.get("correction_mode", "auto")
            if mode != "off":
                corr_hotkey = brain_cfg["correction_hotkey"]
                keyboard.add_hotkey(corr_hotkey, self._open_correction_window, suppress=True)
                log.info("Correction hotkey registered: %s", corr_hotkey)

    def _on_esc(self):
        """Esc handler: cancel if recording, otherwise no-op (passes through)."""
        if self._recording:
            self._cancel_recording()

    def _cancel_recording(self):
        """Cancel in-flight recording: discard buffer, no paste, return to idle."""
        with self._lock:
            if not self._recording:
                return
            self._recording = False
        sounds.play_error()
        log.info("Recording cancelled (Esc)")
        if self._streaming_enabled:
            try:
                self.streaming_recorder.cancel()
            except Exception:
                log.exception("Failed to cancel streaming recorder")
            if self._clipboard_original is not None:
                restore_clipboard(self._clipboard_original)
                self._clipboard_original = None
        else:
            try:
                self.recorder.cancel()
            except Exception:
                log.exception("Failed to cancel recorder")
        self._return_to_idle()
        self._last_action_status = "Cancelled"

    def _copy_last(self, icon=None, item=None):
        """Copy the most recent transcription to the clipboard."""
        if not self._history:
            sounds.play_error()
            return
        import pyperclip
        text = self._history[-1].text
        try:
            pyperclip.copy(text)
            self._last_action_status = "Copied last transcription"
            log.info("Copied last transcription (%d chars)", len(text))
        except Exception:
            log.exception("Copy last failed")
            sounds.play_error()

    def _repaste_last(self):
        """Re-paste the most recent transcription into the currently focused text field."""
        if not self._history:
            sounds.play_error()
            notifications.notify_info("Nothing to re-paste", "History is empty")
            return
        self._repaste_entry(self._history[-1])

    def _repaste_entry(self, entry: HistoryEntry):
        """Re-paste a specific history entry into the focused text field."""
        is_viable, class_name, hwnd = focus_guard.check_text_field()
        if not is_viable:
            sounds.play_error()
            notifications.notify_guard_blocked(class_name)
            return
        method = self.config["ui"]["output_method"]
        try:
            output_text_to_target(entry.text, hwnd, method=method)
            log.info("Re-pasted history entry (%d chars)", len(entry.text))
        except Exception:
            log.exception("Re-paste failed")
            sounds.play_error()

    def _get_history_for_hover(self) -> list:
        """Return entries for the hover panel (newest-last, like the deque)."""
        if not self._show_history_on_hover:
            return []
        return list(self._history)

    def _on_history_repaste(self, entry: HistoryEntry):
        """Hover-panel click — re-paste this entry on a worker thread (Qt-safe)."""
        threading.Thread(
            target=self._repaste_entry, args=(entry,), daemon=True,
        ).start()

    def _on_history_discard(self, entry: HistoryEntry):
        """Hover-panel right-click — drop this entry from history."""
        keep = [e for e in self._history if e is not entry]
        self._history.clear()
        self._history.extend(keep)
        log.info("Discarded history entry (%d remain)", len(self._history))
        self._refresh_tray_menu()

    def _toggle_history_on_hover(self, icon=None, item=None):
        """Flip the privacy toggle for the hover-expand history panel."""
        self._show_history_on_hover = not self._show_history_on_hover
        log.info(
            "Hover-expand history: %s",
            "on" if self._show_history_on_hover else "off",
        )

    def _export_vocabulary(self, icon=None, item=None):
        """Export vocabulary to JSON file."""
        if self._brain is None:
            return
        export_path = Path(__file__).parent / "brain_export.json"
        self._brain.export_to_file(export_path)
        log.info("Vocabulary exported to %s", export_path)

    def _import_vocabulary(self, icon=None, item=None):
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
                lambda item: "Show overlay" if self._recording_indicator.is_dismissed()
                             else "Hide overlay",
                lambda icon, item: self._recording_indicator.toggle_visibility(),
            ),
            pystray.MenuItem(
                "Copy last transcription",
                self._copy_last,
                enabled=lambda item: bool(self._history),
            ),
            pystray.MenuItem(
                lambda item: f"Mode: {self._modes.current().name}  "
                             f"\u2192 next ({self.config['ui'].get('cycle_mode_hotkey', 'ctrl+shift+m')})",
                self._cycle_mode,
            ),
            pystray.Menu.SEPARATOR,
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

    def _quit(self, icon=None, item=None):
        log.info("Shutting down")
        keyboard.unhook_all()
        self._recording_indicator.destroy()
        if self._correction_ui:
            self._correction_ui.destroy()
        if self._brain:
            self._brain.close()
        target = icon if icon is not None else self._icon
        if target is not None:
            target.stop()

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
            "transcriber", _ICON_STATES["idle"], self._tray_tooltip(), menu
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
