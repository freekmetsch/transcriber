"""Correction tracking and auto-learning logic.

Watches for repeated correction patterns and automatically promotes them
to vocabulary entries after a configurable threshold is reached.
"""

import hashlib
import logging

from brain import VocabularyBrain
from prompt_builder import build_initial_prompt

log = logging.getLogger("transcriber.learning")

DEFAULT_AUTO_LEARN_THRESHOLD = 3


def compute_audio_hash(audio_bytes: bytes) -> str:
    """Compute a short SHA-256 hash for an audio buffer (for correction linking)."""
    return hashlib.sha256(audio_bytes).hexdigest()[:16]


def record_correction(
    brain: VocabularyBrain,
    original: str,
    corrected: str,
    *,
    context: str | None = None,
    audio_hash: str | None = None,
    auto_learn_threshold: int = DEFAULT_AUTO_LEARN_THRESHOLD,
) -> dict | None:
    """Log a correction and check if auto-learning should trigger.

    Returns a dict describing the auto-learned term if one was added, else None.

    Auto-learning logic:
    1. Log the correction (original → corrected).
    2. Query how many times this exact pattern has occurred.
    3. If count >= threshold AND the corrected text is not already in vocabulary,
       add it automatically with source='auto'.
    4. Rebuild the initial_prompt cache since vocabulary changed.
    """
    if not original.strip() or not corrected.strip():
        return None

    original = original.strip()
    corrected = corrected.strip()

    # Don't log if nothing actually changed
    if original == corrected:
        return None

    # Log the correction
    brain.log_correction(original, corrected, context=context, audio_hash=audio_hash)

    # Check for auto-learning
    return _check_auto_learn(brain, original, corrected, auto_learn_threshold)


def _check_auto_learn(
    brain: VocabularyBrain,
    original: str,
    corrected: str,
    threshold: int,
) -> dict | None:
    """Check if a correction pattern has hit the auto-learn threshold."""
    patterns = brain.get_correction_patterns(min_count=threshold)

    for pattern in patterns:
        if pattern["original"] == original and pattern["corrected"] == corrected:
            # This pattern has been corrected enough times — auto-learn it
            existing = brain.get_term(corrected)
            if existing is not None:
                # Already in vocabulary — just bump frequency
                brain.increment_frequency(corrected)
                log.info("Bumped frequency for existing term: %s", corrected)
                return None

            # Add as auto-learned vocabulary
            brain.add_term(
                corrected,
                phonetic_hint=original,  # the misrecognition is a useful phonetic hint
                source="auto",
                priority="normal",
            )
            # Rebuild prompt cache since vocabulary changed
            build_initial_prompt(brain)

            learned = {
                "term": corrected,
                "phonetic_hint": original,
                "count": pattern["count"],
            }
            log.info(
                "Auto-learned: %r → %r (after %d corrections)",
                original, corrected, pattern["count"],
            )
            return learned

    return None


def process_correction(
    brain: VocabularyBrain,
    original_text: str,
    corrected_text: str,
    *,
    audio_hash: str | None = None,
    auto_learn_threshold: int = DEFAULT_AUTO_LEARN_THRESHOLD,
) -> list[dict]:
    """Process a full-text correction by finding changed words/phrases.

    Compares original and corrected text word-by-word. For each changed segment,
    logs an individual correction. Returns list of any auto-learned terms.

    This handles the common case where the user only fixes one or two words
    in a longer transcription.
    """
    orig_words = original_text.split()
    corr_words = corrected_text.split()

    # If the texts are very different lengths, treat as a single whole correction
    if abs(len(orig_words) - len(corr_words)) > max(len(orig_words), len(corr_words)) * 0.5:
        result = record_correction(
            brain,
            original_text,
            corrected_text,
            audio_hash=audio_hash,
            auto_learn_threshold=auto_learn_threshold,
        )
        return [result] if result else []

    # Find word-level differences
    learned: list[dict] = []
    i = 0
    while i < min(len(orig_words), len(corr_words)):
        if orig_words[i] != corr_words[i]:
            # Found a difference — expand to capture multi-word corrections
            j = i + 1
            # Look ahead for the next matching word to find the extent of the change
            while j < min(len(orig_words), len(corr_words)) and orig_words[j] != corr_words[j]:
                j += 1

            orig_segment = " ".join(orig_words[i:j])
            corr_segment = " ".join(corr_words[i:j])
            context = " ".join(orig_words[max(0, i - 3):min(len(orig_words), j + 3)])

            result = record_correction(
                brain,
                orig_segment,
                corr_segment,
                context=context,
                audio_hash=audio_hash,
                auto_learn_threshold=auto_learn_threshold,
            )
            if result:
                learned.append(result)
            i = j
        else:
            i += 1

    # Handle trailing words that exist only in one version
    if len(corr_words) > len(orig_words):
        trailing = " ".join(corr_words[len(orig_words):])
        result = record_correction(
            brain,
            "",
            trailing,
            context=" ".join(orig_words[-3:]) if orig_words else None,
            audio_hash=audio_hash,
            auto_learn_threshold=auto_learn_threshold,
        )
        if result:
            learned.append(result)

    return learned
