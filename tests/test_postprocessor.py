"""Tests for Ollama postprocessor fallback and circuit breaker logic."""

import time
from unittest.mock import patch, call

import pytest

import postprocessor
from postprocessor import postprocess_text


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset circuit breaker state before each test."""
    postprocessor._remote_healthy = True
    postprocessor._last_remote_failure = 0.0
    yield


def _make_pp_config(*, fallback_url=None, enabled=True):
    """Build a minimal postprocessing config dict."""
    return {
        "enabled": enabled,
        "model": "qwen2.5:3b",
        "base_url": "http://primary:11434",
        "fallback_url": fallback_url,
        "timeout": 10,
    }


class TestFallbackChain:
    @patch("postprocessor._call_ollama")
    def test_primary_succeeds(self, mock_call):
        """Primary returns result — fallback not called."""
        mock_call.return_value = "Formatted text."
        config = _make_pp_config(fallback_url="http://fallback:11434")

        result = postprocess_text("raw text", config)

        assert result == "Formatted text."
        assert mock_call.call_count == 1
        assert mock_call.call_args[1]["base_url"] == "http://primary:11434"

    @patch("postprocessor._call_ollama")
    def test_primary_fails_fallback_succeeds(self, mock_call):
        """Primary returns None — fallback returns result."""
        mock_call.side_effect = [None, "Fallback formatted."]
        config = _make_pp_config(fallback_url="http://fallback:11434")

        result = postprocess_text("raw text", config)

        assert result == "Fallback formatted."
        assert mock_call.call_count == 2
        # First call to primary, second to fallback
        assert mock_call.call_args_list[0][1]["base_url"] == "http://primary:11434"
        assert mock_call.call_args_list[1][1]["base_url"] == "http://fallback:11434"

    @patch("postprocessor._call_ollama")
    def test_both_fail_returns_raw(self, mock_call):
        """Both endpoints return None — raw text returned."""
        mock_call.return_value = None
        config = _make_pp_config(fallback_url="http://fallback:11434")

        result = postprocess_text("raw text", config)

        assert result == "raw text"
        assert mock_call.call_count == 2

    @patch("postprocessor._call_ollama")
    def test_no_fallback_configured(self, mock_call):
        """No fallback_url — primary fails, raw text returned (backward compat)."""
        mock_call.return_value = None
        config = _make_pp_config(fallback_url=None)

        result = postprocess_text("raw text", config)

        assert result == "raw text"
        assert mock_call.call_count == 1

    @patch("postprocessor._call_ollama")
    def test_disabled_returns_raw(self, mock_call):
        """enabled=False — raw text returned, nothing called."""
        config = _make_pp_config(enabled=False)

        result = postprocess_text("raw text", config)

        assert result == "raw text"
        mock_call.assert_not_called()


class TestCircuitBreaker:
    @patch("postprocessor._call_ollama")
    def test_circuit_breaker_skips_remote(self, mock_call):
        """After primary failure, next call skips primary within cooldown."""
        mock_call.side_effect = [None, "Fallback 1.", "Fallback 2."]
        config = _make_pp_config(fallback_url="http://fallback:11434")

        # First call: primary fails, fallback succeeds
        result1 = postprocess_text("text1", config)
        assert result1 == "Fallback 1."

        # Second call: circuit breaker open, goes straight to fallback
        result2 = postprocess_text("text2", config)
        assert result2 == "Fallback 2."

        # 3 total calls: primary(fail) + fallback(ok) + fallback(ok)
        assert mock_call.call_count == 3
        assert mock_call.call_args_list[0][1]["base_url"] == "http://primary:11434"
        assert mock_call.call_args_list[1][1]["base_url"] == "http://fallback:11434"
        assert mock_call.call_args_list[2][1]["base_url"] == "http://fallback:11434"

    @patch("postprocessor._call_ollama")
    def test_circuit_breaker_resets_on_success(self, mock_call):
        """Successful primary call resets circuit breaker."""
        config = _make_pp_config(fallback_url="http://fallback:11434")

        # Simulate: primary fails, then recovers
        mock_call.side_effect = [None, "Fallback.", "Primary back!"]

        # Call 1: primary fails, fallback works
        postprocess_text("text1", config)
        assert not postprocessor._remote_healthy

        # Force cooldown to expire
        postprocessor._last_remote_failure = time.monotonic() - 61

        # Call 2: cooldown expired, primary re-probed and succeeds
        result = postprocess_text("text2", config)
        assert result == "Primary back!"
        assert postprocessor._remote_healthy

    @patch("postprocessor._call_ollama")
    def test_circuit_breaker_probes_after_cooldown(self, mock_call):
        """After cooldown expires, primary is tried again."""
        config = _make_pp_config(fallback_url="http://fallback:11434")

        # Mark remote as failed in the past (beyond cooldown)
        postprocessor._remote_healthy = False
        postprocessor._last_remote_failure = time.monotonic() - 61

        mock_call.return_value = "Primary recovered."

        result = postprocess_text("text", config)

        assert result == "Primary recovered."
        # Primary was tried (cooldown expired)
        assert mock_call.call_count == 1
        assert mock_call.call_args[1]["base_url"] == "http://primary:11434"
        assert postprocessor._remote_healthy
