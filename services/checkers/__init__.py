from .base import CheckResult, Checker, Issue, REGISTRY, register
from . import spelling, repeats, dutch_dt  # import so @register runs and populates REGISTRY

__all__ = ["REGISTRY", "Checker", "register", "Issue", "CheckResult"]
