"""Escalating timeout tiers based on how many mistakes someone made today.

Pure arithmetic, deliberately free of discord.py so the escalation can be
reasoned about and tested on its own — this decides whether a colleague gets
silenced, which is not the place for logic that can only be checked in
production.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Minutes per tier. The last entry is the ceiling: it repeats forever rather
# than escalating further, so a bad day cannot end in an hour of silence.
DEFAULT_LADDER = (1, 2, 5, 10, 20, 30)
DEFAULT_THRESHOLD = 20

# Discord allows up to 28 days, but anything past a day is a ban with extra
# steps and almost certainly a typo in the ladder.
MAX_MINUTES = 1440

MODE_OFF = "off"
MODE_WARN = "warn"
MODE_MUTE = "mute"

DEFAULT_WARN_TEXT = (
    "⚠️ {user} zit op **{count}** fouten vandaag. "
    "Dat zou een mute van **{minutes}** zijn geweest.\n"
    "_De bot waarschuwt alleen — er wordt nog niemand gedempt._"
)
DEFAULT_MUTE_TEXT = "🔇 {user} is **{minutes}** gemute — **{count}** fouten vandaag."

PLACEHOLDERS = ("{user}", "{count}", "{minutes}")


def parse_ladder(raw: str) -> tuple[int, ...] | None:
    """'1, 2, 5' -> (1, 2, 5). None if any part is not a sane number of minutes."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None

    rungs = []
    for part in parts:
        if not part.isdigit():
            return None
        value = int(part)
        if not 1 <= value <= MAX_MINUTES:
            return None
        rungs.append(value)
    return tuple(rungs)


def tier_for(total: int, threshold: int) -> int:
    """Which tier a daily total lands in. 0 means no punishment yet."""
    if threshold <= 0:
        return 0
    return total // threshold


def minutes_for_tier(tier: int, ladder: tuple[int, ...] = DEFAULT_LADDER) -> int:
    """Timeout length for a tier, capped at the last rung of the ladder."""
    if tier <= 0 or not ladder:
        return 0
    return ladder[min(tier, len(ladder)) - 1]


def crossed(
    previous_total: int, new_total: int, threshold: int, ladder: tuple[int, ...] = DEFAULT_LADDER
) -> int:
    """Minutes to apply, or 0.

    Fires only on the message that pushes someone over a multiple of the
    threshold, never on every message after it. One message can carry several
    mistakes and jump straight past a boundary — from 18 to 21 — which is why
    this compares tiers rather than testing for an exact multiple.
    """
    before = tier_for(previous_total, threshold)
    after = tier_for(new_total, threshold)
    if after <= before:
        return 0
    return minutes_for_tier(after, ladder)


def format_minutes(minutes: int) -> str:
    return "1 minuut" if minutes == 1 else f"{minutes} minuten"


def render(template: str, fallback: str, **values: object) -> str:
    """Fill a template, falling back to the built-in text if it is malformed.

    Admins write these templates by hand, so a stray brace or an invented
    placeholder is a question of when, not if. A broken template must not
    swallow the announcement.
    """
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        log.warning("Custom punishment text is malformed, using the default: %r", template)
        return fallback.format(**values)
