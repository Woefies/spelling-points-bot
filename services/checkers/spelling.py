from spellchecker import SpellChecker  # package is 'pyspellchecker', import name 'spellchecker'

from services.checkers.base import Checker, CheckResult, Issue, register
from services.cleaner import is_noise_word, tokenize


@register("spelling")
class SpellingChecker(Checker):
    def __init__(self):
        self._spell = {"en": SpellChecker(language="en"), "nl": SpellChecker(language="nl")}

    async def check(self, text, lang, ctx) -> CheckResult:
        # detected lang only gates whether we check at all; the actual check runs
        # against every dictionary so code-switched (nl+en) messages don't false-positive.
        if lang not in self._spell:
            return CheckResult()

        whitelist = ctx.get("whitelist", set())
        skip_cap = ctx.get("skip_capitalized", True)

        issues = []
        tokens = tokenize(text)
        candidates = []
        for i, tok in enumerate(tokens):
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

        # a word is only a mistake if unknown in ALL supported dictionaries
        unknown = set(candidates)
        for spell in self._spell.values():
            unknown &= spell.unknown(unknown)
            if not unknown:
                break

        for bad in unknown:
            issues.append(Issue(word=bad, lang=lang, kind="spelling"))

        return CheckResult(issues=issues)
