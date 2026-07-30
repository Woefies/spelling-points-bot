import re

from services.checkers.base import Checker, CheckResult, Issue, register

_REPEAT_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE | re.UNICODE)

# Words that legitimately double in Dutch: "ik denk dat dat goed is", "de mensen
# die die auto zagen", "als hij had had ik gebeld". A real typo on these exists
# but is far rarer than the correct usage, so flagging them costs more than it
# catches.
_ALLOWLIST = {"had", "dat", "die"}


@register("repeats")
class RepeatedWordChecker(Checker):
    async def check(self, text, lang, ctx) -> CheckResult:
        # The per-guild whitelist counts here too. If an admin has declared a word
        # fine, that has to hold for every checker — otherwise whitelisting looks
        # broken to the person who did it.
        whitelist = ctx.get("whitelist", set())

        issues = []
        for m in _REPEAT_RE.finditer(text):
            word = m.group(1).lower()
            if word in _ALLOWLIST or word in whitelist:
                continue
            issues.append(Issue(word=word, lang=lang, kind="repeat"))

        return CheckResult(issues=issues)
