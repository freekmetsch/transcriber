"""Formatting command definitions for dictation post-processing.

Maps spoken formatting commands to their output symbols.
"""

import re


FORMATTING_COMMANDS: dict[str, str] = {
    # Punctuation
    "period": ".",
    "full stop": ".",
    "comma": ",",
    "exclamation mark": "!",
    "question mark": "?",
    "colon": ":",
    "semicolon": ";",
    "dash": " - ",
    # Quotes
    "open quote": "\u201c",
    "close quote": "\u201d",
    # Whitespace / structure
    "new line": "\n",
    "new paragraph": "\n\n",
}

# Pre-build regex: match any command phrase as a whole word (case-insensitive).
# Sort longest-first so "full stop" matches before "full".
_COMMAND_PATTERN = re.compile(
    "|".join(
        re.escape(phrase)
        for phrase in sorted(FORMATTING_COMMANDS, key=len, reverse=True)
    ),
    re.IGNORECASE,
)


def apply_formatting_commands(text: str) -> str:
    """Replace spoken formatting commands with their symbols.

    Case-insensitive. Handles surrounding whitespace so "hello comma world"
    becomes "hello, world" (not "hello , world").
    """
    def _replace(match: re.Match) -> str:
        symbol = FORMATTING_COMMANDS[match.group(0).lower()]
        return symbol

    result = _COMMAND_PATTERN.sub(_replace, text)
    # Clean up extra spaces around punctuation (e.g., "hello , world" -> "hello, world")
    result = re.sub(r"\s+([.,!?;:\u201d])", r"\1", result)
    result = re.sub(r"([\u201c])\s+", r"\1", result)
    # Clean up spaces around newlines (e.g., "hello \n world" -> "hello\nworld")
    result = re.sub(r" +(\n)", r"\1", result)
    result = re.sub(r"(\n) +", r"\1", result)
    return result
