"""PySide6 overlay backend. Public API mirrors recording_indicator_tk.RecordingIndicator.

Runs on a dedicated worker thread (like the Tk backend) so `TranscriberApp.run()`
and `pystray.Icon.run()` keep ownership of the main thread. All public methods
are thread-safe: they emit Qt signals that are delivered to slots on the Qt
worker thread.
"""

import ctypes
import json
import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

log = logging.getLogger("transcriber.recording_indicator_qt")

_POS_FILE = Path(__file__).parent / "indicator_pos.json"

_WIN_W, _WIN_H = 230, 48

_GEAR_X_MAX = 30
_MIC_X_MIN = 50
_MIC_X_MAX = 130
_MODE_X_MIN = 162
_MODE_X_MAX = 206
_CLOSE_X_MIN = 208

_STATE_COLORS = {
    "idle":         "#666666",
    "listening":    "#e0e0e0",
    "transcribing": "#F39C12",
    "processing":   "#4A90D9",
}

_PULSE_COLORS = [
    "#F39C12", "#E8921A", "#D9851F", "#C87820",
    "#C87820", "#D9851F", "#E8921A", "#F39C12",
]

_FEEDBACK_COLORS = {
    "success": "#2ECC71",
    "warning": "#F1C40F",
    "error":   "#E74C3C",
}

_BAR_BG = "#1e1e1e"
_BAR_RADIUS = _WIN_H // 2

_TEXT_POPUP_W = 360
_TEXT_POPUP_H = 32
_TEXT_POPUP_BG = "#2a2a2a"

_HISTORY_PANEL_W = 340
_HISTORY_ROW_H = 30
_HISTORY_PAD = 8
_HISTORY_MAX_ROWS = 3
_HISTORY_OPEN_DELAY_MS = 300
_HISTORY_CLOSE_DELAY_MS = 200

_FADE_DURATION_MS = 140
_TARGET_OPACITY = 0.92
_PULSE_PERIOD_MS = 200

_MICA_MIN_BUILD = 22621  # Windows 11 22H2

# WS_EX_NOACTIVATE — keep previous window focused when the overlay is clicked.
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000


def _set_no_activate(hwnd: int) -> None:
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_NOACTIVATE)
    except Exception:
        log.debug("Could not set WS_EX_NOACTIVATE")


def _mica_supported() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().build >= _MICA_MIN_BUILD


def _apply_mica(hwnd: int) -> None:
    from qframelesswindow import WindowEffect
    WindowEffect(None).setMicaEffect(hwnd, isDarkMode=True, isAlt=False)


def _safe_call(cb: Callable[[], None], label: str) -> None:
    try:
        cb()
    except Exception:
        log.exception("%s callback failed", label)


class _PillWindow(QWidget):
    """Custom-painted pill-shaped overlay with hit zones for gear/mic/mode/close."""

    sig_begin = Signal()
    sig_end = Signal()
    sig_dismiss = Signal()
    sig_restore = Signal()
    sig_toggle_visibility = Signal()
    sig_refresh_mode = Signal()
    sig_set_state = Signal(str)
    sig_show_text = Signal(str, str, float)
    sig_update_level = Signal(float)
    sig_show_feedback = Signal(str)
    sig_destroy = Signal()

    def __init__(self, indicator: "RecordingIndicator"):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self._ind = indicator
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(_WIN_W, _WIN_H)

        self._state = "idle"
        self._dismissed = not indicator._visible_on_start
        self._level_ratio = 0.0
        self._timer_start = 0.0
        self._timer_text = ""
        self._pulse_step = 0
        self._pulse_color: str | None = None
        self._drag_origin: QPointF | None = None
        self._hover_controls = False
        self._text_window: "_TextPopup | None" = None
        self._mica_applied = False

        self._history_panel: "_HistoryPanel | None" = None
        self._history_open_timer = QTimer(self)
        self._history_open_timer.setSingleShot(True)
        self._history_open_timer.setInterval(_HISTORY_OPEN_DELAY_MS)
        self._history_open_timer.timeout.connect(self._try_open_history)
        self._history_close_timer = QTimer(self)
        self._history_close_timer.setSingleShot(True)
        self._history_close_timer.setInterval(_HISTORY_CLOSE_DELAY_MS)
        self._history_close_timer.timeout.connect(self._try_close_history)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(_PULSE_PERIOD_MS)
        self._pulse_timer.timeout.connect(self._tick_pulse)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(_FADE_DURATION_MS)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._fade_on_hide = False

        self.sig_begin.connect(self._slot_begin)
        self.sig_end.connect(self._slot_end)
        self.sig_dismiss.connect(lambda: self._slot_dismiss(notify=True))
        self.sig_restore.connect(self._slot_restore)
        self.sig_toggle_visibility.connect(self._slot_toggle_visibility)
        self.sig_refresh_mode.connect(self.update)
        self.sig_set_state.connect(self._slot_set_state)
        self.sig_show_text.connect(self._slot_show_text)
        self.sig_update_level.connect(self._slot_update_level)
        self.sig_show_feedback.connect(self._slot_show_feedback)
        self.sig_destroy.connect(self._slot_destroy)

    # --- Position persistence ---

    @staticmethod
    def _load_position() -> tuple[int, int] | None:
        try:
            if _POS_FILE.exists():
                data = json.loads(_POS_FILE.read_text(encoding="utf-8"))
                return int(data["x"]), int(data["y"])
        except Exception:
            return None
        return None

    def _save_position(self) -> None:
        try:
            _POS_FILE.write_text(
                json.dumps({"x": self.x(), "y": self.y()}),
                encoding="utf-8",
            )
        except Exception:
            log.debug("Could not save indicator position")

    # --- Painting ---

    def paintEvent(self, event):  # noqa: N802 — Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, _WIN_W, _WIN_H), _BAR_RADIUS, _BAR_RADIUS)
        p.fillPath(path, QColor(_BAR_BG))

        control_color = "#cccccc" if self._hover_controls else "#888888"

        p.setPen(QColor(control_color))
        p.setFont(QFont("Segoe UI Symbol", 12))
        p.drawText(QRect(2, 0, 32, _WIN_H), Qt.AlignCenter, "\u2699")

        mic_color = QColor(
            self._pulse_color if self._pulse_color else _STATE_COLORS.get(self._state, _STATE_COLORS["idle"])
        )
        cx = _WIN_W // 2
        cy = _WIN_H // 2
        self._draw_mic(p, cx, cy, mic_color)

        if self._state == "listening" and self._level_ratio > 0:
            width = self._level_ratio * 50.0
            half = width / 2.0
            p.fillRect(QRectF(cx - half, 42, width, 3), mic_color)

        if self._timer_text:
            p.setPen(QColor("#888888"))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(
                QRect(_MIC_X_MAX, 0, _MODE_X_MIN - _MIC_X_MAX, _WIN_H),
                Qt.AlignCenter, self._timer_text,
            )

        chip_rect = QRectF(_MODE_X_MIN + 2, 15, _MODE_X_MAX - _MODE_X_MIN - 4, 18)
        p.setBrush(QColor("#2a2a2a"))
        p.setPen(QPen(QColor("#555555"), 1))
        p.drawRoundedRect(chip_rect, 4, 4)
        mode_name = self._ind._get_mode_name() if self._ind._get_mode_name else ""
        if mode_name:
            p.setPen(QColor("#bbbbbb"))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(chip_rect, Qt.AlignCenter, mode_name)

        p.setPen(QColor(control_color))
        p.setFont(QFont("Segoe UI", 11, QFont.Bold))
        p.drawText(QRect(_CLOSE_X_MIN, 0, _WIN_W - _CLOSE_X_MIN, _WIN_H),
                   Qt.AlignCenter, "\u2715")

        p.end()

    @staticmethod
    def _draw_mic(p: QPainter, cx: int, cy: int, color: QColor) -> None:
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - 5, cy - 14, 10, 12))
        p.drawRect(QRect(cx - 5, cy - 10, 10, 8))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(color, 2))
        p.drawArc(QRectF(cx - 9, cy - 10, 18, 16), 180 * 16, 180 * 16)
        p.drawLine(cx, cy + 6, cx, cy + 12)
        p.drawLine(cx - 6, cy + 12, cx + 6, cy + 12)

    # --- Events ---

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        hwnd = int(self.winId())
        _set_no_activate(hwnd)
        if not self._mica_applied and _mica_supported():
            try:
                _apply_mica(hwnd)
                self._mica_applied = True
            except Exception:
                log.debug("Mica apply failed; continuing without")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        x = event.position().x()
        if x <= _GEAR_X_MAX:
            self._drag_origin = None
            self._show_menu()
            return
        if x >= _CLOSE_X_MIN:
            self._drag_origin = None
            self._slot_dismiss(notify=True)
            return
        if _MIC_X_MIN <= x <= _MIC_X_MAX:
            self._drag_origin = None
            if self._ind._on_mic_click is not None:
                _safe_call(self._ind._on_mic_click, "on_mic_click")
            return
        if _MODE_X_MIN <= x <= _MODE_X_MAX:
            self._drag_origin = None
            if self._ind._on_mode_click is not None:
                _safe_call(self._ind._on_mode_click, "on_mode_click")
            return
        # Drag elsewhere
        self._drag_origin = event.globalPosition() - QPointF(self.x(), self.y())

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_origin is None:
            return
        new_pos = event.globalPosition() - self._drag_origin
        self.move(int(new_pos.x()), int(new_pos.y()))

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_origin is not None:
            self._drag_origin = None
            self._save_position()

    def enterEvent(self, event):  # noqa: N802
        self._hover_controls = True
        self.update()
        self._history_close_timer.stop()
        if self._history_hover_allowed():
            self._history_open_timer.start()

    def leaveEvent(self, event):  # noqa: N802
        self._hover_controls = False
        self.update()
        self._history_open_timer.stop()
        if self._history_panel is not None and self._history_panel.isVisible():
            self._history_close_timer.start()

    def _history_hover_allowed(self) -> bool:
        if self._dismissed:
            return False
        cb = self._ind._get_history_hover_enabled
        if cb is None:
            return False
        try:
            return bool(cb())
        except Exception:
            log.exception("get_history_hover_enabled failed")
            return False

    def _try_open_history(self) -> None:
        if not self._history_hover_allowed() or not self.isVisible():
            return
        cb = self._ind._get_history_entries
        if cb is None:
            return
        try:
            entries = list(cb() or [])
        except Exception:
            log.exception("get_history_entries failed")
            return
        if not entries:
            return
        if self._history_panel is None:
            self._history_panel = _HistoryPanel(self)
        self._history_panel.set_entries(entries)
        px = self.x() + (_WIN_W - self._history_panel.width()) // 2
        py = self.y() - self._history_panel.height() - 6
        self._history_panel.move(px, py)
        self._history_panel.show()
        self._history_panel.raise_()

    def _try_close_history(self) -> None:
        if self._history_panel is None or not self._history_panel.isVisible():
            return
        if self._hover_controls or self._history_panel.underMouse():
            return
        self._history_panel.hide()

    def _panel_hover_enter(self) -> None:
        self._history_close_timer.stop()

    def _panel_hover_leave(self) -> None:
        if not self._hover_controls:
            self._history_close_timer.start()

    def _hide_history_panel(self) -> None:
        self._history_open_timer.stop()
        self._history_close_timer.stop()
        if self._history_panel is not None and self._history_panel.isVisible():
            self._history_panel.hide()

    def refresh_history_panel(self) -> None:
        """Re-read entries while the panel is visible (called after a discard)."""
        if self._history_panel is None or not self._history_panel.isVisible():
            return
        cb = self._ind._get_history_entries
        if cb is None:
            return
        try:
            entries = list(cb() or [])
        except Exception:
            log.exception("get_history_entries failed")
            return
        if not entries:
            self._history_panel.hide()
            return
        self._history_panel.set_entries(entries)

    def _show_menu(self) -> None:
        items: list = []
        if self._ind._get_menu_items is not None:
            try:
                items = self._ind._get_menu_items() or []
            except Exception:
                log.exception("get_menu_items raised")
                items = []
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #2a2a2a; color: #e0e0e0; font: 10pt 'Segoe UI'; }"
            "QMenu::item:selected { background-color: #444444; color: #ffffff; }"
            "QMenu::separator { height: 1px; background: #444444; margin: 4px 0; }",
        )
        for entry in items:
            if entry is None:
                menu.addSeparator()
                continue
            label, callback = entry
            action = menu.addAction(label)
            if callback is None:
                action.setEnabled(False)
            else:
                action.triggered.connect(
                    lambda _checked=False, cb=callback, l=label: _safe_call(cb, l),
                )
        menu.popup(self.mapToGlobal(self.rect().bottomLeft()))

    # --- Fade helpers ---

    def _fade_in(self) -> None:
        self._fade_on_hide = False
        self._fade_anim.stop()
        self._fade_anim.setStartValue(float(self.windowOpacity()))
        self._fade_anim.setEndValue(_TARGET_OPACITY)
        self._fade_anim.start()

    def _fade_out_and_hide(self) -> None:
        self._fade_on_hide = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(float(self.windowOpacity()))
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_fade_finished(self) -> None:
        if self._fade_on_hide:
            self.hide()
            self.setWindowOpacity(_TARGET_OPACITY)
            self._fade_on_hide = False

    # --- Slots (run on Qt thread) ---

    def _slot_begin(self) -> None:
        if self._dismissed:
            self._slot_restore()
        self._pulse_timer.stop()
        self._pulse_color = None
        self._state = "listening"
        self._level_ratio = 0.0
        self._timer_start = time.monotonic()
        self._timer_text = "0:00"
        self._elapsed_timer.start()
        self.update()

    def _slot_end(self) -> None:
        self._pulse_timer.stop()
        self._pulse_color = None
        self._elapsed_timer.stop()
        self._timer_text = ""
        self._level_ratio = 0.0
        self._state = "idle"
        if self._text_window is not None:
            self._text_window.hide_animated()
        self.update()

    def _slot_dismiss(self, notify: bool) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self._pulse_timer.stop()
        self._elapsed_timer.stop()
        self._timer_text = ""
        if self._text_window is not None:
            self._text_window.hide()
        self._hide_history_panel()
        self._fade_out_and_hide()
        if notify and self._ind._on_dismiss_notify is not None:
            _safe_call(self._ind._on_dismiss_notify, "on_dismiss")

    def _slot_restore(self) -> None:
        if not self._dismissed:
            return
        self._dismissed = False
        self._state = "idle"
        self._level_ratio = 0.0
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade_in()
        self.update()

    def _slot_toggle_visibility(self) -> None:
        if self._dismissed:
            self._slot_restore()
        else:
            self._slot_dismiss(notify=False)

    def _slot_set_state(self, state: str) -> None:
        if state not in _STATE_COLORS:
            return
        prev = self._state
        self._state = state
        self._pulse_timer.stop()
        self._pulse_color = None
        if state == "transcribing":
            self._pulse_step = 0
            self._pulse_timer.start()
        elif state in ("listening", "idle") and prev != state:
            self._level_ratio = 0.0
        self.update()

    def _slot_show_text(self, text: str, language: str, confidence: float) -> None:
        if self._dismissed:
            return
        if self._text_window is None:
            self._text_window = _TextPopup(self)
        self._text_window.show_text(text, language, confidence, anchor=self)

    def _slot_update_level(self, rms: float) -> None:
        if self._state != "listening":
            return
        ratio = min(max(rms, 0.0) / 0.05, 1.0)
        if abs(ratio - self._level_ratio) < 0.01:
            return
        self._level_ratio = ratio
        self.update()

    def _slot_show_feedback(self, feedback_type: str) -> None:
        color = _FEEDBACK_COLORS.get(feedback_type, _FEEDBACK_COLORS["success"])
        was_dismissed = self._dismissed
        if was_dismissed:
            self._slot_restore()
        self._pulse_timer.stop()
        self._pulse_color = color
        self.update()

        def _revert() -> None:
            self._pulse_color = None
            if was_dismissed:
                self._slot_dismiss(notify=False)
            else:
                self._pulse_timer.stop()
                if self._state == "transcribing":
                    self._pulse_step = 0
                    self._pulse_timer.start()
                self.update()

        QTimer.singleShot(350, _revert)

    def _slot_destroy(self) -> None:
        self._pulse_timer.stop()
        self._elapsed_timer.stop()
        self._history_open_timer.stop()
        self._history_close_timer.stop()
        if self._history_panel is not None:
            try:
                self._history_panel.close()
                self._history_panel.deleteLater()
            except RuntimeError:
                pass
            self._history_panel = None
        if self._text_window is not None:
            try:
                self._text_window.close()
                self._text_window.deleteLater()
            except RuntimeError:
                pass  # Already deleted by Qt during shutdown
            self._text_window = None
        try:
            self.close()
        except RuntimeError:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # --- Timer ticks ---

    def _tick_pulse(self) -> None:
        self._pulse_color = _PULSE_COLORS[self._pulse_step % len(_PULSE_COLORS)]
        self._pulse_step += 1
        self.update()

    def _tick_elapsed(self) -> None:
        elapsed = int(time.monotonic() - self._timer_start)
        new_text = f"{elapsed // 60}:{elapsed % 60:02d}"
        if new_text != self._timer_text:
            self._timer_text = new_text
            self.update()


class _TextPopup(QWidget):
    """Transient popup above the pill showing transcribed text + language badge."""

    def __init__(self, parent_window: _PillWindow):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(_TEXT_POPUP_W, _TEXT_POPUP_H)
        self._anchor = parent_window
        self._text = ""
        self._badge = ""
        self._badge_color = QColor("#2ECC71")
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        try:
            _set_no_activate(int(self.winId()))
        except Exception:
            pass

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, _TEXT_POPUP_W, _TEXT_POPUP_H),
                            _TEXT_POPUP_H // 2, _TEXT_POPUP_H // 2)
        p.fillPath(path, QColor(_TEXT_POPUP_BG))
        if self._badge:
            p.setPen(self._badge_color)
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(QRect(14, 0, 40, _TEXT_POPUP_H), Qt.AlignVCenter | Qt.AlignLeft,
                       self._badge)
        if self._text:
            p.setPen(QColor("#cccccc"))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(QRect(12, 0, _TEXT_POPUP_W - 24, _TEXT_POPUP_H),
                       Qt.AlignCenter, self._text)
        p.end()

    def show_text(self, text: str, language: str, confidence: float, anchor: QWidget) -> None:
        display = text if len(text) <= 60 else text[:57] + "\u2026"
        self._text = display
        if language:
            if confidence > 0.8:
                self._badge_color = QColor("#2ECC71")
            elif confidence > 0.5:
                self._badge_color = QColor("#F1C40F")
            else:
                self._badge_color = QColor("#E67E22")
            self._badge = language.upper()
        else:
            self._badge = ""
        tp_x = anchor.x() + (_WIN_W - _TEXT_POPUP_W) // 2
        tp_y = anchor.y() - 40
        self.move(tp_x, tp_y)
        self.show()
        self.raise_()
        self._hide_timer.start(3000)

    def hide_animated(self) -> None:
        self._hide_timer.stop()
        self.hide()


class _HistoryPanel(QWidget):
    """Hover-expand panel showing the last N history entries (newest first).

    Left-click a row → re-paste. Right-click a row → discard that entry.
    Panel width is fixed; height grows with entry count.
    """

    def __init__(self, pill: _PillWindow):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self._pill = pill
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self._entries: list = []
        self._hover_row = -1
        self.resize(_HISTORY_PANEL_W, _HISTORY_PAD * 2 + _HISTORY_ROW_H)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        try:
            _set_no_activate(int(self.winId()))
        except Exception:
            pass

    def set_entries(self, entries: list) -> None:
        # Caller passes newest-last (like a deque). Flip to newest-first for display.
        self._entries = list(reversed(entries))[:_HISTORY_MAX_ROWS]
        rows = max(1, len(self._entries))
        self.resize(_HISTORY_PANEL_W, _HISTORY_PAD * 2 + rows * _HISTORY_ROW_H)
        self._hover_row = -1
        self.update()

    def _row_at(self, y: float) -> int:
        if not self._entries:
            return -1
        idx = (int(y) - _HISTORY_PAD) // _HISTORY_ROW_H
        if 0 <= idx < len(self._entries):
            return int(idx)
        return -1

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 12, 12)
        p.fillPath(path, QColor(_BAR_BG))

        for idx, entry in enumerate(self._entries):
            row_y = _HISTORY_PAD + idx * _HISTORY_ROW_H
            row_rect = QRectF(4, row_y, w - 8, _HISTORY_ROW_H - 2)
            if idx == self._hover_row:
                hov = QPainterPath()
                hov.addRoundedRect(row_rect, 6, 6)
                p.fillPath(hov, QColor("#2f2f2f"))

            ts_text = time.strftime("%H:%M", time.localtime(entry.timestamp))
            p.setPen(QColor("#888888"))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(
                QRect(int(row_rect.x()) + 8, row_y, 40, _HISTORY_ROW_H - 2),
                Qt.AlignVCenter | Qt.AlignLeft, ts_text,
            )

            raw = entry.text or ""
            text = raw if len(raw) <= 60 else raw[:57] + "\u2026"
            p.setPen(QColor("#dddddd"))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(
                QRect(int(row_rect.x()) + 56, row_y,
                      int(row_rect.width()) - 64, _HISTORY_ROW_H - 2),
                Qt.AlignVCenter | Qt.AlignLeft, text,
            )
        p.end()

    def enterEvent(self, event):  # noqa: N802
        self._pill._panel_hover_enter()

    def leaveEvent(self, event):  # noqa: N802
        self._hover_row = -1
        self.update()
        self._pill._panel_hover_leave()

    def mouseMoveEvent(self, event):  # noqa: N802
        new_row = self._row_at(event.position().y())
        if new_row != self._hover_row:
            self._hover_row = new_row
            self.update()

    def mousePressEvent(self, event):  # noqa: N802
        row = self._row_at(event.position().y())
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        ind = self._pill._ind
        if event.button() == Qt.LeftButton:
            self.hide()
            cb = ind._on_history_repaste
            if cb is not None:
                _safe_call(lambda: cb(entry), "on_history_repaste")
        elif event.button() == Qt.RightButton:
            cb = ind._on_history_discard
            if cb is not None:
                _safe_call(lambda: cb(entry), "on_history_discard")
            self._pill.refresh_history_panel()


class RecordingIndicator:
    """Always-visible pill-bar overlay (PySide6 backend).

    Runs Qt on its own worker thread. Public methods are thread-safe — they
    emit Qt signals that are dispatched to slots on the Qt thread.

    States:
      idle         — default; dim mic, no level bar, no timer
      listening    — recording; white mic, live level bar, elapsed timer
      transcribing — working on an utterance; pulsing orange mic
      processing   — post-processing; blue mic

    The pill stays visible from start() until dismiss() is called. end_session()
    transitions to idle but does NOT hide the window.
    """

    def __init__(
        self,
        on_mic_click: Callable[[], None] | None = None,
        on_dismiss: Callable[[], None] | None = None,
        get_menu_items: Callable[[], list] | None = None,
        visible_on_start: bool = True,
        get_mode_name: Callable[[], str] | None = None,
        on_mode_click: Callable[[], None] | None = None,
        get_history_entries: Callable[[], list] | None = None,
        get_history_hover_enabled: Callable[[], bool] | None = None,
        on_history_repaste: Callable[[object], None] | None = None,
        on_history_discard: Callable[[object], None] | None = None,
    ):
        self._on_mic_click = on_mic_click
        self._on_dismiss_notify = on_dismiss
        self._get_menu_items = get_menu_items
        self._visible_on_start = visible_on_start
        self._get_mode_name = get_mode_name
        self._on_mode_click = on_mode_click
        self._get_history_entries = get_history_entries
        self._get_history_hover_enabled = get_history_hover_enabled
        self._on_history_repaste = on_history_repaste
        self._on_history_discard = on_history_discard

        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._app: QApplication | None = None
        self._window: _PillWindow | None = None

    def start(self) -> None:
        """Start the Qt thread. Call once during app init."""
        self._thread = threading.Thread(target=self._run_qt, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_qt(self) -> None:
        if QApplication.instance() is None:
            self._app = QApplication(sys.argv or [""])
        else:
            self._app = QApplication.instance()
        window = _PillWindow(self)
        self._window = window

        saved = _PillWindow._load_position()
        if saved is not None:
            x, y = saved
        else:
            screen = self._app.primaryScreen().geometry()
            x = (screen.width() - _WIN_W) // 2
            y = screen.height() - _WIN_H - 60
        window.move(x, y)

        if self._visible_on_start:
            window.setWindowOpacity(0.0)
            window.show()
            window._fade_in()
        else:
            window.setWindowOpacity(_TARGET_OPACITY)

        self._ready.set()
        self._app.exec()

    # --- Public API (thread-safe) ---

    def begin_session(self) -> None:
        if self._window is not None:
            self._window.sig_begin.emit()

    def end_session(self) -> None:
        if self._window is not None:
            self._window.sig_end.emit()

    def dismiss(self) -> None:
        if self._window is not None:
            self._window.sig_dismiss.emit()

    def restore(self) -> None:
        if self._window is not None:
            self._window.sig_restore.emit()

    def toggle_visibility(self) -> None:
        if self._window is not None:
            self._window.sig_toggle_visibility.emit()

    def is_dismissed(self) -> bool:
        if self._window is not None:
            return self._window._dismissed
        return not self._visible_on_start

    def refresh_mode(self) -> None:
        if self._window is not None:
            self._window.sig_refresh_mode.emit()

    def set_state(self, state: str) -> None:
        if self._window is not None and state in _STATE_COLORS:
            self._window.sig_set_state.emit(state)

    def show_text(self, text: str, language: str = "", confidence: float = 1.0) -> None:
        if self._window is not None:
            self._window.sig_show_text.emit(text, language, float(confidence))

    def update_level(self, rms: float) -> None:
        if self._window is not None:
            self._window.sig_update_level.emit(float(rms))

    def show_feedback(self, feedback_type: str = "success") -> None:
        if self._window is not None:
            self._window.sig_show_feedback.emit(feedback_type)

    def destroy(self) -> None:
        if self._window is not None:
            self._window.sig_destroy.emit()
