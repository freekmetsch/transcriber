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
        "timeout": 10,
    },
    "brain": {
        "enabled": True,
        "db_path": "brain.db",
        "auto_learn_threshold": 3,
        "prompt_max_chars": 500,
        "correction_hotkey": "ctrl+shift+c",
    },
}

CONFIG_PATH = Path(__file__).parent / "config.yaml"


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
    """Load config.yaml and merge with defaults. Missing file is fine — defaults are used."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(DEFAULT_CONFIG, user_config)
        log.info("Loaded config from %s", CONFIG_PATH)
    else:
        config = _deep_merge(DEFAULT_CONFIG, {})  # shallow copy with nested dicts
        log.info("Using default config (no config.yaml found)")
    return config
