"""Text cleaning and tokenization utilities."""
import re

# Fenced code blocks: ```...``` (including language hints, multiline)
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)

# Inline code: `...`
_INLINE_CODE_RE = re.compile(r"`[^`]*`")

# URLs
_URL_RE = re.compile(r"https?://\S+")
_WWW_RE = re.compile(r"www\.\S+")

# Discord mentions: user <@123> / <@!123>, channel <#123>, role <@&123>
_MENTION_RE = re.compile(r"<@!?\d+>|<#\d+>|<@&\d+>")

# Custom discord emoji: <:name:123> or <a:name:123>
_CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")

# Broad unicode emoji range
_UNICODE_EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U0001F000-\U0001F0FF"
    "\U00002600-\U000026FF"
    "\U0001F900-\U0001F9FF"
    "\U00002300-\U000023FF"
    "\U0000FE00-\U0000FE0F"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "]+",
    re.UNICODE,
)

# Digit-containing "words" (e.g. l33t, 123, w0rd)
_DIGIT_WORD_RE = re.compile(r"\b\w*\d\w*\b")

# Unicode-aware word tokenizer: letters only (no digits/underscore), keeps accents
_TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def clean(text: str) -> str:
    """Remove code blocks, URLs, mentions, emoji, and digit-words from text."""
    text = _FENCED_CODE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _WWW_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _CUSTOM_EMOJI_RE.sub(" ", text)
    text = _UNICODE_EMOJI_RE.sub(" ", text)
    text = _DIGIT_WORD_RE.sub(" ", text)
    return text


def tokenize(text: str) -> list[str]:
    """Return unicode-aware word tokens, preserving original case."""
    return _TOKEN_RE.findall(text)


# 3+ identical letters in a row: elongation (lmfaooo, ahhh, yesss, nooo)
_REPEAT_RUN_RE = re.compile(r"(.)\1\1")
# letters that laughter is built from (h + typical laugh vowels/w)
_LAUGH_LETTERS = set("haweoi")


def is_noise_word(word: str) -> bool:
    """True for laughter/elongation non-words (hahaha, wahaha, lmfaooo) that shouldn't be spell-checked."""
    low = word.lower()
    if _REPEAT_RUN_RE.search(low):
        return True
    letters = set(low)
    if len(low) >= 4 and "h" in letters and letters <= _LAUGH_LETTERS:
        return True
    return False
