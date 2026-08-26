import logging

from services.checkers.base import Checker, CheckResult, Issue, register
from services.cleaner import is_noise_word, tokenize
from services.dictionaries import DEFAULT_HUNSPELL_DIR, load

log = logging.getLogger(__name__)


@register("spelling")
class SpellingChecker(Checker):
    def __init__(self):
        # Loaded on first use, not here: @register instantiates at import time,
        # before settings exist, and reading a Hunspell dictionary costs a second
        # or two that should not sit in the import path.
        self._lookups = None
        # Exposed so /status can report which dictionary is actually in use —
        # "is Hunspell live?" is otherwise only answerable from the startup log.
        self.backends: dict = {}

    def _ensure_loaded(self, ctx) -> None:
        if self._lookups is not None:
            return
        self._lookups, self.backends = load(ctx.get("hunspell_dir", DEFAULT_HUNSPELL_DIR))
        backends = self.backends
        log.info(
            "Spelling dictionaries: %s",
            ", ".join(f"{lang}={name}" for lang, name in sorted(backends.items())) or "none",
        )

    def knows(self, word: str, ctx=None) -> bool:
        """True if any loaded dictionary recognises this word.

        Public because the evasion check needs it too: a word the dictionaries
        already know is a real word, not somebody dodging a trigger, and asking a
        model about it would cost money to be told the obvious.
        """
        self._ensure_loaded(ctx or {})
        return any(known(word.lower()) for known in self._lookups.values())

    async def check(self, text, lang, ctx) -> CheckResult:
        self._ensure_loaded(ctx)
        if lang not in self._lookups:
            return CheckResult()

        whitelist = ctx.get("whitelist", set())
        skip_cap = ctx.get("skip_capitalized", True)

        candidates = []
        for i, tok in enumerate(tokenize(text)):
            low = tok.lower()
            if low in whitelist:
                continue
            if len(low) <= 1:
                continue
            if is_noise_word(low):
                continue
            # skip capitalized mid-sentence (likely proper noun): first char upper AND not the first token
            if skip_cap and i > 0 and tok[0].isupper():
                continue
            candidates.append(low)

        # A word only counts as a mistake when no dictionary recognises it, so a
        # message mixing Dutch and English doesn't get punished for either half.
        issues = [
            Issue(word=word, lang=lang, kind="spelling")
            for word in set(candidates)
            if not any(known(word) for known in self._lookups.values())
        ]
        return CheckResult(issues=issues)
