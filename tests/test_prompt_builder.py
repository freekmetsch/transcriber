"""Tests for Whisper prompt builder."""

import pytest

from brain import VocabularyBrain
from prompt_builder import (
    build_initial_prompt,
    get_or_build_prompt,
    get_vocabulary_for_llm,
)


@pytest.fixture
def brain(tmp_path):
    db = VocabularyBrain(tmp_path / "test.db")
    yield db
    db.close()


class TestBuildInitialPrompt:
    def test_empty_vocabulary(self, brain):
        assert build_initial_prompt(brain) == ""

    def test_single_term(self, brain):
        brain.add_term("Freek")
        prompt = build_initial_prompt(brain)
        assert prompt == "Freek"

    def test_multiple_terms(self, brain):
        brain.add_term("Freek")
        brain.add_term("Claude")
        brain.add_term("Anthropic")
        prompt = build_initial_prompt(brain)
        assert "Freek" in prompt
        assert "Claude" in prompt
        assert "Anthropic" in prompt
        # Comma-separated
        assert ", " in prompt

    def test_high_priority_first(self, brain):
        brain.add_term("normal_term")
        brain.add_term("important_term", priority="high")
        prompt = build_initial_prompt(brain)
        # High priority should come before normal
        assert prompt.index("important_term") < prompt.index("normal_term")

    def test_respects_max_chars(self, brain):
        for i in range(100):
            brain.add_term(f"term_{i:03d}")
        prompt = build_initial_prompt(brain, max_chars=50)
        assert len(prompt) <= 50

    def test_caches_prompt(self, brain):
        brain.add_term("Freek")
        build_initial_prompt(brain)
        cached = brain.get_cached_prompt()
        assert cached is not None
        assert "Freek" in cached


class TestGetOrBuildPrompt:
    def test_returns_cached(self, brain):
        brain.cache_prompt("cached prompt")
        assert get_or_build_prompt(brain) == "cached prompt"

    def test_builds_when_no_cache(self, brain):
        brain.add_term("Freek")
        prompt = get_or_build_prompt(brain)
        assert "Freek" in prompt

    def test_force_rebuild(self, brain):
        brain.cache_prompt("old cached prompt")
        brain.add_term("NewTerm")
        prompt = get_or_build_prompt(brain, force_rebuild=True)
        assert "NewTerm" in prompt

    def test_empty_when_no_terms_no_cache(self, brain):
        assert get_or_build_prompt(brain) == ""


class TestGetVocabularyForLLM:
    def test_empty(self, brain):
        assert get_vocabulary_for_llm(brain) == ""

    def test_basic_terms(self, brain):
        brain.add_term("Freek")
        brain.add_term("Claude")
        text = get_vocabulary_for_llm(brain)
        assert "- Freek" in text
        assert "- Claude" in text

    def test_with_phonetic_hint(self, brain):
        brain.add_term("Freek", phonetic_hint="freak")
        text = get_vocabulary_for_llm(brain)
        assert "Freek" in text
        assert "sounds like: freak" in text

    def test_without_phonetic_hint(self, brain):
        brain.add_term("Claude")
        text = get_vocabulary_for_llm(brain)
        assert "- Claude" in text
        assert "sounds like" not in text
