"""Per-guild overrides for the settings that shape the spelling check.

These started as environment variables, which meant tuning them needed shell
access to the host and a restart. They are the knobs you actually reach for when
the bot turns out too strict or too noisy — the emergency brake — so they have to
be reachable from Discord. The `.env` value stays the default; a guild overrides
it or leaves it alone.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# key -> (attribute on Settings, kind)
FIELDS = {
    "spelling_enabled": ("spelling_enabled", "bool"),
    "points_per_mistake": ("points_per_mistake", "int"),
    "reply_on_mistake": ("reply_on_mistake", "bool"),
    "min_words_for_detect": ("min_words_for_detect", "int"),
    "skip_capitalized": ("skip_capitalized", "bool"),
}

LABELS = {
    "spelling_enabled": "spelling controleren",
    "points_per_mistake": "punten per fout",
    "reply_on_mistake": "antwoorden bij een fout",
    "min_words_for_detect": "minimum aantal woorden",
    "skip_capitalized": "woorden met hoofdletter overslaan",
}


def _coerce(raw: str, kind: str):
    if kind == "bool":
        return raw == "1"
    return int(raw)


def resolve(stored: dict[str, str], defaults) -> dict:
    """Merge a guild's stored overrides over the .env defaults."""
    out = {}
    for key, (attr, kind) in FIELDS.items():
        fallback = getattr(defaults, attr)
        raw = stored.get(key)
        if raw is None:
            out[key] = fallback
            continue
        try:
            out[key] = _coerce(raw, kind)
        except ValueError:
            # A hand-edited or restored database can hold anything; a bad value
            # must not stop the bot from checking messages.
            log.warning("Setting %s holds %r, falling back to %r", key, raw, fallback)
            out[key] = fallback
    return out


def store(value) -> str:
    return "1" if value is True else "0" if value is False else str(value)


def describe(key: str, value) -> str:
    if isinstance(value, bool):
        return "aan" if value else "uit"
    return str(value)
