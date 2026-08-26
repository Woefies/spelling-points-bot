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
# A verdict is one word. Anything longer is the model ignoring its instructions,
# and cutting it off there keeps a runaway answer cheap.
JUDGE_MAX_TOKENS = 8
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


JUDGE_SYSTEM = (
    "Je beoordeelt of iemand een chatfilter probeert te omzeilen door een woord "
    "anders te schrijven. Antwoord met exact een woord: JA of NEE. "
    "JA alleen als het duidelijk hetzelfde woord is, verdraaid of verlengd om het "
    "filter te ontwijken. NEE bij een gewoon Nederlands of Engels woord, bij een "
    "naam, bij een typefout, en altijd bij twijfel."
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


async def _ask(system: str, prompt: str, max_tokens: int, what: str) -> str | None:
    """One short completion, or None if anything at all goes wrong.

    Every caller in this module goes through here, so the timeout, the disabled
    thinking and the swallow-everything contract are stated once.
    """
    key = api_key()
    if not key:
        return None

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        log.warning("anthropic package not installed — AI features disabled")
        return None

    try:
        client = AsyncAnthropic(api_key=key, timeout=TIMEOUT_SECONDS)
        response = await asyncio.wait_for(
            client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                # Neither a one-line joke nor a yes/no verdict needs deliberation,
                # and every second here is a second the channel waits.
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=TIMEOUT_SECONDS + 1,
        )
    except asyncio.TimeoutError:
        log.warning("AI %s timed out after %.0fs", what, TIMEOUT_SECONDS)
        return None
    except Exception:
        log.exception("AI %s failed", what)
        return None

    if response.stop_reason == "refusal":
        log.info("AI declined: %s", what)
        return None

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


async def generate(persona: str, prompt: str) -> str | None:
    """A trigger reply in the guild's own voice, or None to use the stored text."""
    return await _ask(f"{persona}\n\n{GUARDRAILS}", prompt, MAX_TOKENS, "reply")


def build_judge_prompt(pattern: str, word: str, message: str | None) -> str:
    """What the model is asked in order to judge one word.

    Never carries the persona: a bot written to be sarcastic must not become a
    harsher judge because of it. This is a question of fact, not of voice.
    """
    lines = [
        f'Het filter let op het woord: "{pattern.split("|")[0]}".',
        f'Iemand schreef: "{word}".',
    ]
    if message:
        lines.append(f'Het hele bericht was: "{message[:400]}"')
    lines.append("Is dit een poging om het filter te omzeilen? JA of NEE.")
    return "\n".join(lines)


def parse_verdict(raw: str | None) -> bool | None:
    """JA / NEE, or None for anything else.

    Strict on purpose. An answer this code cannot read is not a "maybe" that
    leans either way — it is no answer, and the caller must treat it as such
    rather than guessing, because guessing here mutes someone.
    """
    if not raw:
        return None
    first = raw.strip().upper().split()[0].strip(".,:;!?\"'()")
    if first == "JA":
        return True
    if first == "NEE":
        return False
    log.warning("Unreadable evasion verdict %r", raw[:60])
    return None


async def judge_evasion(pattern: str, word: str, message: str | None) -> bool | None:
    """True if the word dodges the trigger, False if not, None if unknown."""
    raw = await _ask(
        JUDGE_SYSTEM, build_judge_prompt(pattern, word, message), JUDGE_MAX_TOKENS, "verdict"
    )
    return parse_verdict(raw)


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
