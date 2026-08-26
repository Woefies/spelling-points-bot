"""Which of the three ways the bot should treat one channel.

A test channel exists because every other way of trying something out has a cost
on this server: a new trigger, a reworked persona or a changed threshold is
otherwise tried in a room full of colleagues, and a mistake there is a real point
on someone's tally or a real mute.

Three states, resolved per message:

  * ``LIVE``  — normal. Points count, triggers log, mutes happen.
  * ``TEST``  — the sandbox. The bot reacts exactly as it would, and records
    nothing at all: no points, no ``issues_log`` row, no trigger hit, no timeout.
  * ``MUTED`` — isolate mode is on and this is not the sandbox, so the bot stays
    out of this channel entirely.

Everything here is deliberately failure-open: an unset, unreadable or
half-configured setting resolves to ``LIVE``. Silencing the bot has to be
something someone chose on purpose, never something a bad value did by accident.
"""

import logging

log = logging.getLogger(__name__)

CONFIG_CHANNEL = "test_channel"
CONFIG_ISOLATE = "test_isolate"

LIVE = "live"
TEST = "test"
MUTED = "muted"

# Appended to whatever the bot would have said in the sandbox, so a message in
# the test channel can never be mistaken for one that counted.
MARKER = "🧪 _Testkanaal — niets hiervan is opgeslagen._"


def test_channel_id(config: dict[str, str]) -> int | None:
    """The configured sandbox channel, or None if there is none to speak of."""
    raw = config.get(CONFIG_CHANNEL)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("test_channel holds %r, ignoring it", raw)
        return None


def isolated(config: dict[str, str]) -> bool:
    """Isolate only means anything once a sandbox channel exists.

    Without that pair the setting would silence the bot everywhere with nowhere
    left to switch it back on from — a trap rather than a mode.
    """
    return config.get(CONFIG_ISOLATE) == "1" and test_channel_id(config) is not None


def state(config: dict[str, str], channel_id: int, parent_id: int | None = None) -> str:
    """How this channel should be treated, given the guild's stored config.

    `parent_id` is the thread's parent, so a thread started inside the test
    channel is part of the sandbox rather than a live channel of its own.
    """
    test_id = test_channel_id(config)
    if test_id is None:
        return LIVE
    if channel_id == test_id or parent_id == test_id:
        return TEST
    return MUTED if config.get(CONFIG_ISOLATE) == "1" else LIVE


def state_for(config: dict[str, str], channel) -> str:
    """`state()` for a discord channel object, threads included."""
    return state(config, channel.id, getattr(channel, "parent_id", None))
