"""Catching deliberate misspellings of a trigger word.

`compile_phrases` matches a trigger on exact word boundaries, which is what keeps
it off `kankeren` and `borstkanker`. The cost of that precision is that anyone who
wants to dodge a trigger only has to change one character: `br3nt`, `brenttt`,
`b r e n t`, `brentify`.

Two tiers, because they are not the same problem:

  * **Obfuscation** (`obfuscations`) — the same word with the letters dressed up:
    digits standing in for letters, letters repeated, separators pushed between
    them. Once normalised these are *identical* to the trigger word, so no
    judgement is involved and no AI is needed. Deterministic, free, offline.

  * **Near misses** (`near_misses`) — a genuinely different word that is built
    around the trigger word (`brentify`, `brentje`) or one edit away from it
    (`brant`). Whether that is a dodge or an innocent word is a judgement call
    that depends on what the trigger means, so these are only *candidates*; a
    model decides, and only if the guild switched that on.

Nothing here reaches a verdict on a near miss by itself. That separation is the
point: the free tier can never be wrong about what it claims, and the tier that
can be wrong is opt-in and reviewable.
"""

import re
import unicodedata

# Characters people substitute for letters. Deliberately short: every entry is a
# chance to collide with a legitimate word, and these are the ones that actually
# turn up in chat.
LEET = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "@": "a", "$": "s", "!": "i", "|": "l", "€": "e",
}

# How much longer than the trigger a word may be and still read as built around
# it. "brentify" yes, a paragraph that happens to contain the letters no.
MAX_EXTRA_LETTERS = 6

# Below this, one edit is most of the word and everything resembles everything.
# It also gates the "built around" rule: a two-letter core turns up inside far
# too many ordinary words to be worth a model's opinion.
MIN_CORE_LENGTH = 4

# A two-letter spaced pattern would fire on ordinary abbreviations.
MIN_SPACED_LETTERS = 3

_TOKEN_RE = re.compile(r"[^\s]+")
# Letters only: no separators, so nothing was pushed apart.
_PLAIN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def core(text: str) -> str:
    """The letters someone was actually trying to type, runs left intact.

    Accents folded, digits and symbols mapped back to letters, everything else
    dropped. Keeping the runs is what lets `kkr` stay distinguishable from `kr`.
    """
    folded = unicodedata.normalize("NFKD", text.lower())
    letters = []
    for char in folded:
        if unicodedata.combining(char):
            continue
        char = LEET.get(char, char)
        if char.isalpha():
            letters.append(char)
    return "".join(letters)


def normalize(text: str) -> str:
    """`core()` with runs of the same letter collapsed, so `brenttt` reads as `brent`.

    Collapsing is symmetric — it is applied to the trigger word too — which on its
    own would make `kr` indistinguishable from `kkr`. Callers guard that by
    refusing any word whose `core()` is shorter than the trigger's: an elongation
    is never shorter than what it elongates.
    """
    collapsed: list[str] = []
    for char in core(text):
        if not collapsed or collapsed[-1] != char:
            collapsed.append(char)
    return "".join(collapsed)


def _letters(text: str) -> str:
    """The phrase's letters, accents folded, nothing collapsed."""
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in folded if not unicodedata.combining(c) and c.isalpha())


def spaced_pattern(phrase: str) -> re.Pattern[str] | None:
    """Match a phrase whose letters have been pushed apart: `b r e n t`.

    Built from the phrase's own letters rather than its normalised form: `kkr`
    has to stay `k?k?r` here, or the pattern degrades to `k?r` and starts firing
    on any stray "kr". Only non-letters may sit between them and the whole run
    still has to fall on word boundaries, so `brentify` is not matched by this
    and neither is any word that merely contains the letters.
    """
    letters = list(_letters(phrase))
    if len(letters) < MIN_SPACED_LETTERS:
        return None
    body = r"[\W_]*".join(re.escape(c) for c in letters)
    return re.compile(rf"\b{body}\b", re.IGNORECASE | re.UNICODE)


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, abandoned as soon as it exceeds `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                previous[j - 1] if ca == cb
                else 1 + min(previous[j - 1], previous[j], current[j - 1])
            )
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _phrases(pattern: str) -> list[str]:
    return [p.strip() for p in pattern.split("|") if p.strip()]


def obfuscations(text: str, pattern: str) -> list[str]:
    """Words in `text` that *are* the trigger word, only dressed up.

    Returns the words as they were written, so the bot can quote them back.
    Certain enough to act on without asking anyone.
    """
    # (collapsed form, how many letters the real phrase has)
    targets = {(normalize(p), len(core(p))) for p in _phrases(pattern)}
    targets = {t for t in targets if t[0]}
    if not targets:
        return []

    found = []
    for word in _TOKEN_RE.findall(text):
        collapsed, length = normalize(word), len(core(word))
        # A dodge dresses the word up; it never makes it shorter. Without this,
        # collapsing runs on both sides would read "kr" as the trigger "kkr".
        if any(collapsed == t and length >= n for t, n in targets):
            found.append(word)

    for phrase in _phrases(pattern):
        spaced = spaced_pattern(phrase)
        if spaced is None:
            continue
        for match in spaced.finditer(text):
            written = match.group(0)
            # Nothing between the letters means this is the plain word, which the
            # ordinary trigger match already handles or already rejected.
            if _PLAIN_RE.fullmatch(written):
                continue
            found.append(written)

    return _dedupe(found)


def near_misses(text: str, pattern: str, skip: set[str]) -> list[str]:
    """Words that *might* be a dodge, for something else to judge.

    `skip` holds words that must never be offered up — the guild whitelist and
    anything the dictionaries recognise as a real word. A word an admin has
    whitelisted has to be fine for every checker, or whitelisting looks broken to
    the person who did it.
    """
    targets = [normalize(p) for p in _phrases(pattern)]
    targets = [t for t in targets if t]
    if not targets:
        return []

    found = []
    for word in _TOKEN_RE.findall(text):
        if word.lower() in skip:
            continue
        norm = normalize(word)
        if not norm or norm in targets or norm in skip:
            continue

        for target in targets:
            if len(target) < MIN_CORE_LENGTH:
                continue
            built_around = (
                target in norm and 0 < len(norm) - len(target) <= MAX_EXTRA_LETTERS
            )
            one_edit = (
                len(norm) >= MIN_CORE_LENGTH and _edit_distance(norm, target, 1) <= 1
            )
            if built_around or one_edit:
                found.append(word)
                break

    return _dedupe(found)


def _dedupe(words: list[str]) -> list[str]:
    """One entry per underlying word: `b.r.e.n.t.` and `b.r.e.n.t` are one dodge."""
    seen, unique = set(), []
    for word in words:
        key = normalize(word)
        if key not in seen:
            seen.add(key)
            unique.append(word)
    return unique
