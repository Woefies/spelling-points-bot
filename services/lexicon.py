"""Built-in chat-slang skip list: Dutch+English internet abbreviations/interjections
that should never be counted as spelling mistakes. Merged into the whitelist skip path.
"""

CHAT_SLANG = frozenset({
    # English
    "idk", "tbh", "imo", "imho", "btw", "ngl", "fr", "ez", "gg", "pog", "based",
    "nvm", "rn", "wyd", "wdym", "hmu", "ftw", "istg", "afaik", "lmao", "lmfao",
    "lmfaoo", "lol",
    "rofl", "smh", "irl", "tldr", "dm", "gtg", "brb", "bruh", "meh", "ugh",
    "pff", "oof", "yikes", "yep", "nope", "yup", "nah", "huh", "eh", "oi", "xd",
    # Dutch
    "idd", "gwn", "wrm", "ff", "mss", "egt", "ofzo", "tog", "kzn", "ofc", "iig",
    "sws", "hoezo", "joh", "nou", "mkay", "oke", "aub", "svp",
    # Dutch contractions (apostrophe forms preserved by tokenizer)
    "m'n", "z'n", "d'r", "'t",
})
