"""Message variants: one stored string, several possible phrasings.

Recurring output (daily reminders, keyword responses) goes stale fast when it is
always literally the same sentence, so a message may hold several variants
separated by '|' and one is picked per firing.
"""

import random
import re

SEPARATOR = "|"


def split_variants(text: str) -> list[str]:
    return [part.strip() for part in text.split(SEPARATOR) if part.strip()]


def pick_variant(text: str) -> str:
    """Pick one variant at random. Text without a separator passes through unchanged."""
    variants = split_variants(text)
    return random.choice(variants) if variants else text


def compile_phrases(pattern: str) -> re.Pattern[str]:
    """Build a case-insensitive, word-bounded regex from '|'-separated phrases.

    Word boundaries matter: 'kanker' must not fire on 'kankeren', and 'kkr' must
    not fire inside a longer word.
    """
    phrases = split_variants(pattern) or [pattern.strip()]
    alternatives = "|".join(re.escape(p) for p in phrases)
    return re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE | re.UNICODE)
