"""Build Whisper initial_prompt from vocabulary database.

The initial_prompt parameter biases Whisper's decoder toward expected vocabulary,
reducing word error rate on domain-specific terms by ~25%.
"""

import logging

from brain import VocabularyBrain

log = logging.getLogger("transcriber.prompt_builder")

# Whisper's initial_prompt is tokenized — keep it under this many characters
# to avoid truncation and wasted context. ~500 chars ≈ ~120 tokens.
DEFAULT_MAX_CHARS = 500


def build_initial_prompt(
    brain: VocabularyBrain,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Generate an initial_prompt string from the vocabulary database.

    Strategy:
    1. High-priority terms always included first.
    2. Remaining terms added by frequency until the character budget is spent.
    3. Terms are joined with commas — this gives Whisper natural token boundaries.

    The result is cached in the brain DB so it doesn't need to be rebuilt every call.
    """
    terms = brain.get_all_term_strings()  # already sorted: high priority first, then by frequency
    if not terms:
        return ""

    # Build the prompt within the character budget
    parts: list[str] = []
    current_len = 0
    for term in terms:
        # +2 for ", " separator
        addition = len(term) + (2 if parts else 0)
        if current_len + addition > max_chars:
            break
        parts.append(term)
        current_len += addition

    prompt = ", ".join(parts)

    # Cache it
    brain.cache_prompt(prompt)
    log.info("Built initial_prompt: %d terms, %d chars", len(parts), len(prompt))

    return prompt


def get_or_build_prompt(
    brain: VocabularyBrain,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    force_rebuild: bool = False,
) -> str:
    """Return the cached prompt if available, otherwise build a new one.

    Call with force_rebuild=True after vocabulary changes to refresh the cache.
    """
    if not force_rebuild:
        cached = brain.get_cached_prompt()
        if cached is not None:
            return cached

    return build_initial_prompt(brain, max_chars=max_chars)


def get_vocabulary_for_llm(brain: VocabularyBrain) -> str:
    """Build a vocabulary list for the LLM post-processing prompt.

    Returns a formatted string of terms that the LLM should recognize and prefer
    when cleaning up transcriptions.
    """
    terms = brain.get_all_terms()
    if not terms:
        return ""

    lines: list[str] = []
    for entry in terms:
        term = entry["term"]
        hint = entry.get("phonetic_hint")
        if hint:
            lines.append(f"- {term} (sounds like: {hint})")
        else:
            lines.append(f"- {term}")

    return "\n".join(lines)
