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
# Bounds on what an admin may dial these to. A timeout long enough to be worth
# raising is already long enough to make the channel feel stuck, and one below a
# couple of seconds would fail on a perfectly healthy call.
MIN_TIMEOUT, MAX_TIMEOUT = 2.0, 15.0
DEFAULT_CANDIDATES = 3
MIN_CANDIDATES, MAX_CANDIDATES = 1, 10

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


KEY_NAME = "ANTHROPIC_API_KEY"


def api_key() -> str | None:
    return os.getenv(KEY_NAME) or None


def key_state() -> tuple[str, list[str]]:
    """How the key is missing, and any near-miss variable names.

    "Not set" and "set but empty" look identical from `api_key()` and have
    completely different fixes, so they are separated here. The near-miss list
    catches the other recurring cause — a typo in the variable name, which
    otherwise presents as "the whole file is being ignored" and sends people
    looking in the wrong place entirely.

    Names only. The value never leaves this function.
    """
    raw = os.environ.get(KEY_NAME)
    if raw is None:
        state = "absent"
    elif not raw.strip():
        state = "empty"
    else:
        state = "present"

    similar = sorted(
        name
        for name in os.environ
        if name != KEY_NAME
        and ("ANTHROP" in name.upper() or "ANTROPH" in name.upper() or "CLAUDE" in name.upper())
    )
    return state, similar


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


# Newer request options. An older anthropic SDK, or an older API surface behind
# the same key, rejects these outright — so a failure that names one of them is
# retried without them rather than reported as "no answer".
_TUNING = {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}


def _rejects_tuning(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return isinstance(exc, TypeError) or any(
        name in text for name in ("thinking", "output_config", "effort", "unexpected keyword")
    )


def _explain(exc: Exception) -> str:
    """Turn an SDK exception into something an admin can act on.

    The three that actually happen with a fresh key: no credit, wrong key, wrong
    model name. Anything else falls through with its own text, truncated.
    """
    text = f"{exc}".lower()
    status = getattr(exc, "status_code", None)
    if status == 401 or "authentication" in text or "invalid x-api-key" in text:
        return "De sleutel wordt geweigerd. Klopt hij, en is hij niet ingetrokken?"
    if "credit balance" in text or "billing" in text or status == 402:
        return (
            "Er staat geen tegoed op het Anthropic-account. Opwaarderen in de "
            "Console onder Billing."
        )
    if status == 404 or ("model" in text and "not_found" in text):
        return f"Het model {MODEL} bestaat niet voor dit account."
    if status == 429:
        return "Te veel aanvragen tegelijk. Even wachten."
    return f"{type(exc).__name__}: {exc}"[:300]


async def _ask(
    system: str, prompt: str, max_tokens: int, what: str, timeout: float = TIMEOUT_SECONDS
) -> tuple[str | None, str | None]:
    """(answer, why there is none). Never raises.

    Every caller in this module goes through here, so the timeout and the
    swallow-everything contract are stated once. The reason is returned rather
    than only logged, because the people who configure this bot do not have
    shell access to the machine it runs on — "check the logs" is not a usable
    instruction for them.
    """
    key = api_key()
    if not key:
        return None, "Er is geen API-sleutel."

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        log.warning("anthropic package not installed — AI features disabled")
        return None, (
            "Het pakket `anthropic` zit niet in de image. Rebuild met "
            "`docker compose up -d --build`."
        )

    client = AsyncAnthropic(api_key=key, timeout=timeout)
    body = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }

    # First with the tuning options, then without. Neither a one-line joke nor a
    # yes/no verdict needs deliberation, but not being able to say so is no
    # reason to fall silent.
    for attempt, extra in enumerate((_TUNING, {})):
        try:
            response = await asyncio.wait_for(
                client.messages.create(**body, **extra),
                # Outer guard as well as the client's own: a client that never
                # settles would otherwise hold the message handler open.
                timeout=timeout + 1,
            )
        except asyncio.TimeoutError:
            log.warning("AI %s timed out after %.1fs", what, timeout)
            return None, f"Geen antwoord binnen {timeout:g} seconden."
        except Exception as exc:
            if attempt == 0 and _rejects_tuning(exc):
                log.warning("AI %s: retrying without tuning options (%s)", what, exc)
                continue
            log.exception("AI %s failed", what)
            return None, _explain(exc)

        if response.stop_reason == "refusal":
            log.info("AI declined: %s", what)
            return None, "Het model wilde hier niet op antwoorden."

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return (text, None) if text else (None, "Het model gaf een leeg antwoord.")

    return None, "Onbekende fout."


async def generate(persona: str, prompt: str, timeout: float = TIMEOUT_SECONDS) -> str | None:
    """A trigger reply in the guild's own voice, or None to use the stored text."""
    text, _ = await generate_verbose(persona, prompt, timeout)
    return text


async def generate_verbose(
    persona: str, prompt: str, timeout: float = TIMEOUT_SECONDS
) -> tuple[str | None, str | None]:
    """As `generate`, but also says why there is no answer. Used by /ai test."""
    return await _ask(f"{persona}\n\n{GUARDRAILS}", prompt, MAX_TOKENS, "reply", timeout)


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


async def judge_evasion(
    pattern: str, word: str, message: str | None, timeout: float = TIMEOUT_SECONDS
) -> bool | None:
    """True if the word dodges the trigger, False if not, None if unknown."""
    raw, _ = await _ask(
        JUDGE_SYSTEM,
        build_judge_prompt(pattern, word, message),
        JUDGE_MAX_TOKENS,
        "verdict",
        timeout,
    )
    return parse_verdict(raw)


def clamp(value: float, low: float, high: float) -> float:
    """Keep a stored setting inside its bounds.

    Applied on read as well as on write: a hand-edited or restored database can
    hold anything, and a nonsense timeout must not be able to stall the channel.
    """
    return max(low, min(high, value))


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
