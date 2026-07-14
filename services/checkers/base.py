from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Issue:
    word: str
    lang: str
    kind: str


@dataclass
class CheckResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.issues)


class Checker(ABC):
    name: str = "base"

    @abstractmethod
    async def check(self, text: str, lang: str, ctx: dict) -> CheckResult: ...


REGISTRY: dict[str, "Checker"] = {}


def register(name):
    def deco(cls):
        cls.name = name
        REGISTRY[name] = cls()  # instantiate once, store instance
        return cls

    return deco


# ctx dict passed to check() has keys:
#   "whitelist": set[str] (lowercased words to ignore)
#   "skip_capitalized": bool
