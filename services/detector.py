"""Language detection utilities."""
from langdetect import DetectorFactory, LangDetectException
from langdetect import detect as _ld_detect

DetectorFactory.seed = 0  # deterministic results

_SUPPORTED = {"en": "en", "nl": "nl"}


def detect(text: str, min_words: int = 3) -> str | None:
    """Detect language of text, returning 'en', 'nl', or None."""
    words = text.split()
    if len(words) < min_words:
        return None
    try:
        lang = _ld_detect(text)
    except LangDetectException:
        return None
    return _SUPPORTED.get(lang)
