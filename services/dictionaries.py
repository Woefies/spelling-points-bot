"""Dictionary backends for the spelling checker.

Hunspell where its dictionaries are installed, pyspellchecker otherwise. The
fallback matters: a checkout without the system packages, or a container built
before they were added, still has to run rather than fail at import.

Hunspell is the better backend for Dutch by a wide margin, because it applies
affix and compounding rules instead of matching a flat list. Words like
"zonnebrandcrème" and "voetbalwedstrijdverslag" are not in any word list and
never can be — Dutch glues words together without limit — but Hunspell derives
them. That is the single biggest source of false positives in this bot.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

DEFAULT_HUNSPELL_DIR = "/usr/share/hunspell"

# Debian's hunspell-nl / hunspell-en-us install nl_NL and en_US; OpenTaal's own
# release is plain nl. Try each in order and take the first that exists.
_STEMS = {
    "nl": ("nl_NL", "nl", "nl_BE"),
    "en": ("en_US", "en_GB", "en"),
}

Lookup = Callable[[str], bool]


def _hunspell_lookup(stem: Path) -> Lookup | None:
    try:
        from spylls.hunspell import Dictionary
    except ImportError:
        return None

    try:
        dic = Dictionary.from_files(str(stem))
    except Exception:
        log.exception("Hunspell dictionary at %s could not be read", stem)
        return None

    # spylls is a readable reference implementation rather than a fast one, and
    # chat repeats the same words constantly, so the cache earns its keep.
    @lru_cache(maxsize=50_000)
    def known(word: str) -> bool:
        return bool(dic.lookup(word))

    return known


def _pyspellchecker_lookup(lang: str) -> Lookup | None:
    try:
        from spellchecker import SpellChecker

        spell = SpellChecker(language=lang)
    except Exception:
        log.exception("pyspellchecker has no dictionary for %r", lang)
        return None

    @lru_cache(maxsize=50_000)
    def known(word: str) -> bool:
        return not spell.unknown([word])

    return known


def load(hunspell_dir: str = DEFAULT_HUNSPELL_DIR) -> tuple[dict[str, Lookup], dict[str, str]]:
    """Build a lookup per language. Returns (lookups, backend name per language)."""
    base = Path(hunspell_dir)
    lookups: dict[str, Lookup] = {}
    backends: dict[str, str] = {}

    for lang, stems in _STEMS.items():
        for stem in stems:
            if not (base / f"{stem}.dic").exists():
                continue
            lookup = _hunspell_lookup(base / stem)
            if lookup is not None:
                lookups[lang] = lookup
                backends[lang] = f"hunspell:{stem}"
                break

        if lang not in lookups:
            lookup = _pyspellchecker_lookup(lang)
            if lookup is not None:
                lookups[lang] = lookup
                backends[lang] = "pyspellchecker"

    return lookups, backends
