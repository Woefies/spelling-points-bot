"""Escalating timeout tiers based on how many mistakes someone made today.

Pure arithmetic, deliberately free of discord.py so the escalation can be
reasoned about and tested on its own — this decides whether a colleague gets
silenced, which is not the place for logic that can only be checked in
production.
"""

from __future__ import annotations

# Minutes per tier. The last entry is the ceiling: it repeats forever rather
# than escalating further, so a bad day cannot end in an hour of silence.
LADDER_MINUTES = (1, 2, 5, 10, 20, 30)

DEFAULT_THRESHOLD = 20

MODE_OFF = "off"
MODE_WARN = "warn"
MODE_MUTE = "mute"
MODES = (MODE_OFF, MODE_WARN, MODE_MUTE)


def tier_for(total: int, threshold: int) -> int:
    """Which tier a daily total lands in. 0 means no punishment yet."""
    if threshold <= 0:
        return 0
    return total // threshold


def minutes_for_tier(tier: int) -> int:
    """Timeout length for a tier, capped at the last rung of the ladder."""
    if tier <= 0:
        return 0
    return LADDER_MINUTES[min(tier, len(LADDER_MINUTES)) - 1]


def crossed(previous_total: int, new_total: int, threshold: int) -> int:
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
    return minutes_for_tier(after)
