"""Tests for correction tracking and auto-learning."""

import pytest

from brain import VocabularyBrain
from learning import record_correction, process_correction


@pytest.fixture
def brain(tmp_path):
    db = VocabularyBrain(tmp_path / "test.db")
    yield db
    db.close()


class TestRecordCorrection:
    def test_logs_correction(self, brain):
        record_correction(brain, "Freak", "Freek")
        assert brain.correction_count() == 1

    def test_ignores_empty(self, brain):
        result = record_correction(brain, "", "Freek")
        assert result is None
        assert brain.correction_count() == 0

    def test_ignores_no_change(self, brain):
        result = record_correction(brain, "Freek", "Freek")
        assert result is None
        assert brain.correction_count() == 0

    def test_strips_whitespace(self, brain):
        record_correction(brain, "  Freak  ", "  Freek  ")
        corrections = brain.get_corrections()
        assert corrections[0]["original"] == "Freak"
        assert corrections[0]["corrected"] == "Freek"

    def test_no_auto_learn_below_threshold(self, brain):
        result = record_correction(brain, "Freak", "Freek", auto_learn_threshold=3)
        assert result is None
        result = record_correction(brain, "Freak", "Freek", auto_learn_threshold=3)
        assert result is None
        # Still below threshold
        assert brain.term_count() == 0

    def test_auto_learn_at_threshold(self, brain):
        for _ in range(2):
            record_correction(brain, "Freak", "Freek", auto_learn_threshold=3)
        # Third time triggers auto-learn
        result = record_correction(brain, "Freak", "Freek", auto_learn_threshold=3)
        assert result is not None
        assert result["term"] == "Freek"
        assert result["phonetic_hint"] == "Freak"
        assert result["count"] == 3
        # Term should now be in vocabulary
        assert brain.get_term("Freek") is not None
        entry = brain.get_term("Freek")
        assert entry["source"] == "auto"
        assert entry["phonetic_hint"] == "Freak"

    def test_auto_learn_bumps_existing(self, brain):
        brain.add_term("Freek")
        for _ in range(3):
            record_correction(brain, "Freak", "Freek", auto_learn_threshold=3)
        # Should bump frequency, not add duplicate
        assert brain.term_count() == 1
        entry = brain.get_term("Freek")
        assert entry["frequency"] == 1  # bumped once on the 3rd correction

    def test_auto_learn_rebuilds_prompt_cache(self, brain):
        for _ in range(3):
            record_correction(brain, "Freak", "Freek", auto_learn_threshold=3)
        cached = brain.get_cached_prompt()
        assert cached is not None
        assert "Freek" in cached

    def test_custom_threshold(self, brain):
        # With threshold=1, first correction auto-learns
        result = record_correction(brain, "Freak", "Freek", auto_learn_threshold=1)
        assert result is not None
        assert brain.get_term("Freek") is not None


class TestProcessCorrection:
    def test_single_word_change(self, brain):
        learned = process_correction(
            brain,
            "Hello Freak how are you",
            "Hello Freek how are you",
            auto_learn_threshold=1,
        )
        assert len(learned) == 1
        assert learned[0]["term"] == "Freek"
        corrections = brain.get_corrections()
        assert corrections[0]["original"] == "Freak"
        assert corrections[0]["corrected"] == "Freek"

    def test_no_change(self, brain):
        learned = process_correction(brain, "Hello world", "Hello world")
        assert learned == []
        assert brain.correction_count() == 0

    def test_multi_word_change(self, brain):
        learned = process_correction(
            brain,
            "I use Claude coat",
            "I use Claude Code",
            auto_learn_threshold=1,
        )
        assert any(e["term"] == "Code" for e in learned)

    def test_very_different_texts_treated_as_whole(self, brain):
        # When texts are very different, treat as single correction
        original = "completely wrong transcription"
        corrected = "the actual words I said were different"
        process_correction(brain, original, corrected)
        assert brain.correction_count() == 1
        corrections = brain.get_corrections()
        assert corrections[0]["original"] == original
        assert corrections[0]["corrected"] == corrected

    def test_context_captured(self, brain):
        process_correction(
            brain,
            "Hello Freak how are you",
            "Hello Freek how are you",
        )
        corrections = brain.get_corrections()
        assert corrections[0]["context"] is not None
        assert "Freak" in corrections[0]["context"] or "Freek" in corrections[0]["context"]
