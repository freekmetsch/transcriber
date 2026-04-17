"""Dictation modes — switchable polish/output profiles.

A mode bundles a human-facing name with two knobs the dictation pipeline
reads: a polish-prompt addendum (appended to the cloud system prompt) and
an output_format ("default" or "raw"). "raw" skips cloud polish and local
formatting-command substitution, useful for dictating code or identifiers.

Modes load from config.yaml (`modes:` list) with DEFAULT_MODES as fallback.
The currently selected mode index persists to mode_state.json.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("transcriber.modes")


@dataclass(frozen=True)
class Mode:
    name: str
    polish_prompt_addendum: str = ""
    output_format: str = "default"  # "default" | "raw"


DEFAULT_MODES: list[Mode] = [
    Mode(name="Default"),
    Mode(
        name="Email",
        polish_prompt_addendum=(
            "Format as a polite professional email body. Preserve the user's tone."
        ),
    ),
    Mode(name="Code", output_format="raw"),
]


def load_modes(config_section: list[dict] | None) -> list[Mode]:
    """Build modes from a config.yaml list; fall back to DEFAULT_MODES if missing/invalid."""
    if not config_section:
        return list(DEFAULT_MODES)
    modes: list[Mode] = []
    for entry in config_section:
        try:
            modes.append(Mode(
                name=str(entry["name"]),
                polish_prompt_addendum=str(entry.get("polish_prompt_addendum", "")),
                output_format=str(entry.get("output_format", "default")),
            ))
        except (KeyError, TypeError):
            log.warning("Skipping invalid mode entry: %r", entry)
    return modes or list(DEFAULT_MODES)


class ModeManager:
    """Holds the mode list + persistent current index. Thread-safety: cycle/current
    are called only from the app thread or Tk-after callbacks; no lock needed."""

    def __init__(self, modes: list[Mode], state_path: Path):
        if not modes:
            raise ValueError("ModeManager needs at least one Mode")
        self._modes = modes
        self._state_path = state_path
        self._index = self._load_index()

    def _load_index(self) -> int:
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                idx = int(data.get("current_index", 0))
                if 0 <= idx < len(self._modes):
                    return idx
        except (OSError, ValueError, TypeError):
            log.debug("Could not read mode state; starting at 0")
        return 0

    def _save_index(self) -> None:
        try:
            self._state_path.write_text(
                json.dumps({"current_index": self._index}), encoding="utf-8"
            )
        except OSError:
            log.debug("Could not persist mode state")

    def current(self) -> Mode:
        return self._modes[self._index]

    def cycle(self) -> Mode:
        """Advance to the next mode and persist. Returns the new current mode."""
        self._index = (self._index + 1) % len(self._modes)
        self._save_index()
        return self.current()

    def names(self) -> list[str]:
        return [m.name for m in self._modes]
