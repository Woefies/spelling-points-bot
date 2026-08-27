"""Reading the free-text fields of a Discord form back into values.

A modal only ever hands back strings, so anything that is a number, a yes/no or
a channel somewhere else is text here. These helpers do that conversion in one
place, and every one of them answers "I could not read that" with None rather
than raising or guessing — a form is filled in by hand, and a typo in one field
must produce a sentence explaining it, not a traceback.

The empty string is meaningful and never an error: it is how someone says
"clear this field".
"""

import re

# Discord's own ceiling for one modal text input. Nothing in this bot may
# invent a tighter limit than the platform imposes — a field that refuses text
# the platform would have accepted is a limit nobody asked for.
MODAL_MAX = 4000

# Everything a Dutch speaker plausibly types for yes, and for no. Anything else
# is not a third option, it is a typo, and is reported as one.
_YES = {"ja", "j", "aan", "true", "waar", "1", "y", "yes", "on"}
_NO = {"nee", "n", "uit", "false", "onwaar", "0", "no", "off"}

_CHANNEL_RE = re.compile(r"<#(\d+)>|^(\d{5,25})$")


def read_bool(raw: str, default: bool = False) -> bool | None:
    """ja/nee to a bool. Empty keeps `default`; anything unreadable is None."""
    text = raw.strip().lower()
    if not text:
        return default
    if text in _YES:
        return True
    if text in _NO:
        return False
    return None


def read_optional_int(raw: str, low: int, high: int) -> int | None | str:
    """A whole number in range, None for empty, or an error message.

    The three-way return is deliberate: "not filled in" and "filled in wrongly"
    are different outcomes and the caller has to be able to tell them apart.
    """
    text = raw.strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        return f"`{text[:30]}` is geen getal."
    if not low <= value <= high:
        return f"Vul een getal van {low} tot {high} in, niet {value}."
    return value


def read_channel(raw: str) -> int | None | str:
    """A channel ID from `<#123>`, a bare ID, or an error message."""
    text = raw.strip()
    if not text:
        return None
    match = _CHANNEL_RE.search(text)
    if not match:
        return (
            f"`{text[:30]}` is geen kanaal. Plak het kanaal (`#naam` wordt "
            "automatisch omgezet) of vul het ID in."
        )
    return int(match.group(1) or match.group(2))


def write_bool(value: bool) -> str:
    return "ja" if value else "nee"
