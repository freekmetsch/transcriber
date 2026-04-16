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
        "silence_threshold": 0.01,
        "silence_duration_ms": 600,
        "min_segment_ms": 500,
        "max_segment_s": 30,
    },
    "ui": {
        "sounds": True,
        "output_method": "auto",   # auto | type | paste
        "auto_start": False,
    },
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

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)
        log.info("Loaded config from %s", CONFIG_PATH)
    else:
        log.info("No config.yaml found, using defaults")

    if LOCAL_CONFIG_PATH.exists():
        with open(LOCAL_CONFIG_PATH, encoding="utf-8") as f:
            local_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, local_config)
        log.info("Applied local overrides from %s", LOCAL_CONFIG_PATH)

    return config
