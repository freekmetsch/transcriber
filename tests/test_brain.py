"""Tests for the VocabularyBrain SQLite database."""

import json
import tempfile
from pathlib import Path

import pytest

from brain import VocabularyBrain


@pytest.fixture
def brain(tmp_path):
    """Create a brain with a temporary database."""
    db = VocabularyBrain(tmp_path / "test_brain.db")
    yield db
    db.close()


class TestVocabularyCRUD:
    def test_add_term(self, brain):
        row_id = brain.add_term("Freek")
        assert row_id is not None
        assert brain.term_count() == 1

    def test_add_duplicate_returns_none(self, brain):
        brain.add_term("Freek")
        assert brain.add_term("Freek") is None
        assert brain.term_count() == 1

    def test_add_duplicate_case_insensitive(self, brain):
        brain.add_term("Freek")
        assert brain.add_term("freek") is None
        assert brain.term_count() == 1

    def test_remove_term(self, brain):
        brain.add_term("Freek")
        assert brain.remove_term("Freek") is True
        assert brain.term_count() == 0

    def test_remove_nonexistent(self, brain):
        assert brain.remove_term("nope") is False

    def test_get_term(self, brain):
        brain.add_term("Freek", phonetic_hint="freak", priority="high")
        entry = brain.get_term("Freek")
        assert entry is not None
        assert entry["term"] == "Freek"
        assert entry["phonetic_hint"] == "freak"
        assert entry["priority"] == "high"
        assert entry["source"] == "manual"
        assert entry["frequency"] == 0

    def test_get_term_case_insensitive(self, brain):
        brain.add_term("Freek")
        assert brain.get_term("freek") is not None

    def test_get_nonexistent(self, brain):
        assert brain.get_term("nope") is None

    def test_get_all_terms(self, brain):
        brain.add_term("alpha")
        brain.add_term("beta", priority="high")
        brain.add_term("gamma")
        terms = brain.get_all_terms()
        assert len(terms) == 3
        # High priority first
        assert terms[0]["term"] == "beta"

    def test_get_all_term_strings(self, brain):
        brain.add_term("alpha")
        brain.add_term("beta", priority="high")
        strings = brain.get_all_term_strings()
        assert strings == ["beta", "alpha"]

    def test_get_high_priority_terms(self, brain):
        brain.add_term("alpha")
        brain.add_term("beta", priority="high")
        brain.add_term("gamma", priority="high")
        high = brain.get_high_priority_terms()
        assert set(high) == {"beta", "gamma"}

    def test_update_term(self, brain):
        brain.add_term("Freek")
        assert brain.update_term("Freek", priority="high") is True
        entry = brain.get_term("Freek")
        assert entry["priority"] == "high"

    def test_update_nonexistent(self, brain):
        assert brain.update_term("nope", priority="high") is False

    def test_update_invalid_field_ignored(self, brain):
        brain.add_term("Freek")
        assert brain.update_term("Freek", invalid_field="x") is False

    def test_increment_frequency(self, brain):
        brain.add_term("Freek")
        brain.increment_frequency("Freek")
        brain.increment_frequency("Freek")
        entry = brain.get_term("Freek")
        assert entry["frequency"] == 2

    def test_increment_nonexistent(self, brain):
        assert brain.increment_frequency("nope") is False


class TestCorrections:
    def test_log_correction(self, brain):
        row_id = brain.log_correction("Freak", "Freek")
        assert row_id is not None
        assert brain.correction_count() == 1

    def test_get_corrections(self, brain):
        brain.log_correction("Freak", "Freek", context="Hi Freak")
        brain.log_correction("teh", "the")
        corrections = brain.get_corrections()
        assert len(corrections) == 2
        # Newest first (by rowid — both may share the same timestamp)
        originals = {c["original"] for c in corrections}
        assert originals == {"Freak", "teh"}

    def test_get_correction_patterns(self, brain):
        brain.log_correction("Freak", "Freek")
        brain.log_correction("Freak", "Freek")
        brain.log_correction("Freak", "Freek")
        brain.log_correction("teh", "the")
        patterns = brain.get_correction_patterns(min_count=2)
        assert len(patterns) == 1
        assert patterns[0]["original"] == "Freak"
        assert patterns[0]["corrected"] == "Freek"
        assert patterns[0]["count"] == 3

    def test_get_correction_patterns_all(self, brain):
        brain.log_correction("Freak", "Freek")
        brain.log_correction("teh", "the")
        patterns = brain.get_correction_patterns(min_count=1)
        assert len(patterns) == 2


class TestPromptCache:
    def test_cache_and_retrieve(self, brain):
        brain.cache_prompt("Freek, Claude, Python")
        assert brain.get_cached_prompt() == "Freek, Claude, Python"

    def test_cache_replaces_old(self, brain):
        brain.cache_prompt("old prompt")
        brain.cache_prompt("new prompt")
        assert brain.get_cached_prompt() == "new prompt"

    def test_no_cache(self, brain):
        assert brain.get_cached_prompt() is None


class TestSettings:
    def test_set_and_get(self, brain):
        brain.set_setting("theme", "dark")
        assert brain.get_setting("theme") == "dark"

    def test_get_default(self, brain):
        assert brain.get_setting("missing", "fallback") == "fallback"

    def test_upsert(self, brain):
        brain.set_setting("theme", "dark")
        brain.set_setting("theme", "light")
        assert brain.get_setting("theme") == "light"


class TestJsonExportImport:
    def test_export(self, brain, tmp_path):
        brain.add_term("Freek", phonetic_hint="freak")
        brain.log_correction("Freak", "Freek")
        data = brain.export_json()
        assert len(data["vocabulary"]) == 1
        assert len(data["corrections"]) == 1
        assert data["schema_version"] == 1

    def test_export_to_file(self, brain, tmp_path):
        brain.add_term("Freek")
        export_path = tmp_path / "export.json"
        brain.export_to_file(export_path)
        assert export_path.exists()
        data = json.loads(export_path.read_text(encoding="utf-8"))
        assert len(data["vocabulary"]) == 1

    def test_import_from_file(self, brain, tmp_path):
        # Create export from one brain
        brain.add_term("Freek", phonetic_hint="freak")
        brain.log_correction("Freak", "Freek")
        export_path = tmp_path / "export.json"
        brain.export_to_file(export_path)

        # Import into a fresh brain
        brain2 = VocabularyBrain(tmp_path / "brain2.db")
        brain2.import_from_file(export_path)
        assert brain2.term_count() == 1
        assert brain2.correction_count() == 1
        assert brain2.get_term("Freek")["phonetic_hint"] == "freak"
        brain2.close()

    def test_import_merge_no_duplicates(self, brain, tmp_path):
        brain.add_term("Freek")
        export_path = tmp_path / "export.json"
        brain.export_to_file(export_path)
        # Import again — should not duplicate
        brain.import_from_file(export_path)
        assert brain.term_count() == 1


class TestThreadSafety:
    def test_wal_mode(self, brain):
        """Verify WAL mode is active for concurrent access."""
        row = brain._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
