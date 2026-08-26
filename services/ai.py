"""Generated trigger replies via the Claude API.

Deliberately narrow. This is the only place in the bot that talks to an external
service, and it is wrapped in three guards, because a joke reply is never worth
a stalled channel or a surprise bill:

  * a per-day call budget that hard-stops,
  * a short timeout — a slow reply is worse than a static one,
  * a fallback to the trigger's own stored text on any failure at all.

The bot must never go quiet because a network call went wrong.
"""

import asyncio
import logging
import os

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
MAX_TOKENS = 300
TIMEOUT_SECONDS = 5.0
DEFAULT_BUDGET = 50

DEFAULT_PERSONA = (
    "Je bent een Discord-bot op de werkvloer van een klein Nederlands bedrijf. "
    "Je reageert kort en droog op wat collega's zeggen. Nooit meer dan twee zinnen."
)

# Sent on every call, after the persona. Keeps the guards in the model's own
# instructions rather than relying on the persona author to remember them.
GUARDRAILS = (
    "Antwoord in het Nederlands, in maximaal twee korte zinnen. "
    "Geen aanhalingstekens om je antwoord. Geen uitleg over wat je doet. "
    "Verzin geen feiten over mensen. Blijf luchtig en beledig niemand persoonlijk."
)


def api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY") or None


def build_prompt(pattern: str, count: int, message: str | None) -> str:
    """What the model is told about the situation.

    `message` is None unless the guild opted into sending message content — the
    default keeps colleagues' actual messages off the wire, and the trigger word
    plus a hit count is enough for a one-liner.
    """
    lines = [f"Iemand zei een woord waar jij op let: \"{pattern.split('|')[0]}\"."]
    if count > 1:
        lines.append(f"Dat is de {count}e keer voor deze persoon.")
    if message:
        lines.append(f"Het bericht was: \"{message[:400]}\"")
    lines.append("Schrijf jouw reactie.")
    return "\n".join(lines)


async def generate(persona: str, prompt: str) -> str | None:
    """One short completion, or None if anything at all goes wrong."""
    key = api_key()
    if not key:
        return None

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        log.warning("anthropic package not installed — AI replies disabled")
        return None

    try:
        client = AsyncAnthropic(api_key=key, timeout=TIMEOUT_SECONDS)
        response = await asyncio.wait_for(
            client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                # A one-line joke needs no deliberation, and every second here is
                # a second the channel waits.
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                system=f"{persona}\n\n{GUARDRAILS}",
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=TIMEOUT_SECONDS + 1,
        )
    except asyncio.TimeoutError:
        log.warning("AI reply timed out after %.0fs", TIMEOUT_SECONDS)
        return None
    except Exception:
        log.exception("AI reply failed")
        return None

    if response.stop_reason == "refusal":
        log.info("AI declined to answer this trigger")
        return None

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


def parse_usage(raw: str | None, today: str) -> int:
    """Stored as 'YYYY-MM-DD:count'; a different date means the budget resets."""
    if not raw or ":" not in raw:
        return 0
    day, _, count = raw.partition(":")
    if day != today:
        return 0
    try:
        return int(count)
    except ValueError:
        return 0


def format_usage(today: str, count: int) -> str:
    return f"{today}:{count}"
