import re

from services.checkers.base import Checker, CheckResult, Issue, register

_REPEAT_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE | re.UNICODE)
_ALLOWLIST = {"had"}


@register("repeats")
class RepeatedWordChecker(Checker):
    async def check(self, text, lang, ctx) -> CheckResult:
        issues = []
        for m in _REPEAT_RE.finditer(text):
            word = m.group(1).lower()
            if word in _ALLOWLIST:
                continue
            issues.append(Issue(word=word, lang=lang, kind="repeat"))

        return CheckResult(issues=issues)
