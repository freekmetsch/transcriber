"""PySide6 overlay backend. Public API mirrors recording_indicator_tk.RecordingIndicator."""

from collections.abc import Callable


class RecordingIndicator:
    def __init__(
        self,
        on_mic_click: Callable[[], None] | None = None,
        on_dismiss: Callable[[], None] | None = None,
        get_menu_items: Callable[[], list] | None = None,
        visible_on_start: bool = True,
        get_mode_name: Callable[[], str] | None = None,
        on_mode_click: Callable[[], None] | None = None,
    ):
        self._on_mic_click = on_mic_click
        self._on_dismiss_notify = on_dismiss
        self._get_menu_items = get_menu_items
        self._visible_on_start = visible_on_start
        self._get_mode_name = get_mode_name
        self._on_mode_click = on_mode_click
        self._dismissed = not visible_on_start

    def start(self) -> None:
        raise NotImplementedError

    def begin_session(self) -> None:
        raise NotImplementedError

    def end_session(self) -> None:
        raise NotImplementedError

    def dismiss(self) -> None:
        raise NotImplementedError

    def restore(self) -> None:
        raise NotImplementedError

    def toggle_visibility(self) -> None:
        raise NotImplementedError

    def is_dismissed(self) -> bool:
        return self._dismissed

    def refresh_mode(self) -> None:
        raise NotImplementedError

    def set_state(self, state: str) -> None:
        raise NotImplementedError

    def show_text(self, text: str, language: str = "", confidence: float = 1.0) -> None:
        raise NotImplementedError

    def update_level(self, rms: float) -> None:
        raise NotImplementedError

    def show_feedback(self, feedback_type: str = "success") -> None:
        raise NotImplementedError

    def destroy(self) -> None:
        raise NotImplementedError
