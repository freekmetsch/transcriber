"""Configuration loading from config.yaml with sensible defaults."""

import logging
from pathlib import Path

import yaml

log = logging.getLogger("transcriber.config")

DEFAULT_CONFIG = {
    "hotkey": "ctrl+shift+space",
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "device": None,
    },
    "whisper": {
        "model_size": "large-v3",
        "device": "cuda",
        "compute_type": "float16",
        "cloud": {
            "enabled": True,
            "provider": "groq",
            # Groq two-call path (default):
            "stt_model": "whisper-large-v3-turbo",
            "polish_model": "llama-3.3-70b-versatile",
            "stt_timeout": 1.0,
            "polish_timeout": 1.2,
            "groq_base_url": "https://api.groq.com/openai/v1",
            # OpenRouter audio-chat alternative (set provider: openrouter to use):
            "model": "openai/gpt-audio",
            "base_url": "https://openrouter.ai/api/v1",
            # Common:
            "api_key": "",
            "referer": "https://github.com/freekmetsch/transcriber",
            "title": "Transcriber",
            "timeout": 2.0,
            "failure_threshold": 3,
            "cooldown_s": 60.0,
        },
    },
    "postprocessing": {
        "enabled": True,
        "model": "qwen2.5:3b",
        "base_url": "http://localhost:11434",
        "fallback_url": None,
        "timeout": 10,
    },
    "brain": {
        "enabled": True,
        "db_path": "brain.db",
        "auto_learn_threshold": 3,
        "prompt_max_chars": 500,
        "correction_hotkey": "ctrl+shift+c",
        "correction_mode": "auto",
        "correction_timeout": 8,
        "notifications": True,
    },
    "streaming": {
        "enabled": True,
        "vad": {
            "engine": "silero",
            "threshold": 0.5,
            "min_silence_ms": 600,
            "speech_pad_ms": 120,
            "preroll_ms": 300,
        },
        # EnergyVAD overrides (only used when vad.engine == "energy").
        "silence_threshold": 0.01,
        "silence_duration_ms": 600,
        "min_segment_ms": 500,
        "max_segment_s": 30,
    },
    "ui": {
        "sounds": True,
        "output_method": "auto",   # auto | type | paste
        "auto_start": False,
        "show_level_meter": True,
        "show_language": True,
        "overlay_visible_on_start": True,
        "toggle_overlay_hotkey": "ctrl+shift+h",
        "cycle_mode_hotkey": "ctrl+shift+m",
    },
    # Dictation modes — None means use built-in defaults (Default, Email, Code).
    "modes": None,
}

CONFIG_PATH = Path(__file__).parent / "config.yaml"
LOCAL_CONFIG_PATH = Path(__file__).parent / "config.local.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """Load config, with optional local overrides for machine-specific settings.

    Merge order: defaults → config.yaml → config.local.yaml
    config.local.yaml is gitignored, so each machine can have its own overrides.
    """
    config = DEFAULT_CONFIG.copy()

    tracked_api_key = ""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)
        log.info("Loaded config from %s", CONFIG_PATH)
        tracked_api_key = (
            (user_config.get("whisper") or {})
            .get("cloud", {})
            .get("api_key", "")
        )
    else:
        log.info("No config.yaml found, using defaults")

    if LOCAL_CONFIG_PATH.exists():
        with open(LOCAL_CONFIG_PATH, encoding="utf-8") as f:
            local_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, local_config)
        log.info("Applied local overrides from %s", LOCAL_CONFIG_PATH)

    if tracked_api_key:
        log.error(
            "SECURITY: whisper.cloud.api_key is set in TRACKED config.yaml — "
            "move it to config.local.yaml (gitignored) to avoid leaking it."
        )

    return config
