"""Formatting command definitions for dictation post-processing (EN + NL).

Maps spoken formatting commands to their output symbols.
Both English and Dutch variants are included for bilingual code-switching support.
"""

FORMATTING_COMMANDS: dict[str, str] = {
    # Punctuation
    "period": ".",
    "punt": ".",
    "full stop": ".",
    "comma": ",",
    "komma": ",",
    "exclamation mark": "!",
    "uitroepteken": "!",
    "question mark": "?",
    "vraagteken": "?",
    "colon": ":",
    "dubbele punt": ":",
    "semicolon": ";",
    "puntkomma": ";",
    "dash": " - ",
    "streepje": " - ",
    # Quotes
    "open quote": "\u201c",
    "aanhalingsteken openen": "\u201c",
    "close quote": "\u201d",
    "aanhalingsteken sluiten": "\u201d",
    # Whitespace / structure
    "new line": "\n",
    "nieuwe regel": "\n",
    "new paragraph": "\n\n",
    "nieuw alinea": "\n\n",
}
