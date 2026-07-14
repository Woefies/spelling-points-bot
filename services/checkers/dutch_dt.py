import re

from services.checkers.base import Checker, CheckResult, Issue, register

_COMP = "groter|beter|meer|minder|sneller|hoger|lager|ouder|jonger|mooier|duurder|kleiner|slechter|dikker|langer|korter|slimmer|sterker|zwakker|leuker|erger"

_RULES = [
    (
        re.compile(
            r"\bhun\s+(?:hebben|zijn|gaan|willen|kunnen|moeten|zullen|hadden|waren|worden|doen|zaten|gingen)\b",
            re.I,
        ),
        "hun→zij",
    ),
    (
        re.compile(r"\b(?:hij|het|dat|dit|die|er|men|ie)\s+word\b", re.I),
        "word→wordt",
    ),
    (
        re.compile(r"\bik\s+wordt\b", re.I),
        "wordt→word",
    ),
    (
        re.compile(rf"\b(?:{_COMP})\s+als\b", re.I),
        "als→dan",
    ),
]


@register("dutch_dt")
class DutchGrammarChecker(Checker):
    async def check(self, text, lang, ctx) -> CheckResult:
        if lang != "nl":
            return CheckResult()

        issues = []
        for regex, label in _RULES:
            for _ in regex.finditer(text):
                issues.append(Issue(word=label, lang="nl", kind="grammar_nl"))

        return CheckResult(issues=issues)
