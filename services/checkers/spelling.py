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

    def _ensure_loaded(self, ctx) -> None:
        if self._lookups is not None:
            return
        self._lookups, backends = load(ctx.get("hunspell_dir", DEFAULT_HUNSPELL_DIR))
        log.info(
            "Spelling dictionaries: %s",
            ", ".join(f"{lang}={name}" for lang, name in sorted(backends.items())) or "none",
        )

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
