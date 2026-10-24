import re
import unicodedata


def normalize_text(text: str) -> str:
    """
    Cleans and standardizes raw Telegram message text:
    - Normalizes Unicode (NFKC)
    - Replaces non-standard whitespace, zero-width chars, and unicode spaces
    - Standardizes various dashes and hyphens to '-'
    - Removes markdown links (retains link anchor text, strips URLs)
    - Strips dangerous characters/patterns
    """
    if not text:
        return ""

    # Unicode NFKC normalization
    text = unicodedata.normalize("NFKC", text)

    # Remove zero-width spaces and invisible characters
    invisible_chars = [
        "\u200b", "\u200c", "\u200d", "\ufeff", "\u200e", "\u200f", "\ufe0f",
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e"
    ]
    for char in invisible_chars:
        text = text.replace(char, "")

    # Standardize non-breaking and special spaces
    text = re.sub(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", text)

    # Standardize various hyphens/dashes to standard '-'
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2043]", "-", text)

    # Standardize various unicode arrows to '->'
    text = re.sub(r"[\u2190-\u21ff\u2790-\u27bf\u25b6\u25b7]", "->", text)

    # Neutralize markdown links: [Link text](http://...) -> Link text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Strip telegram markdown bold/underline formatting tokens (**, __)
    # 1. First remove intra-word markdown tokens so words are not broken apart (e.g. LON**G -> LONG, Q**USD -> QUSD, AVA**/USD -> AVA/USD, **$BR** -> $BR)
    text = re.sub(r"([A-Za-z0-9])(\*\*+|__+)([/A-Za-z0-9])", r"\1\3", text)
    # 2. Then remove any remaining formatting tokens
    text = re.sub(r"(\*\*+|__+)", "", text)

    # Fix author typos where space was typed instead of a decimal point in price (e.g. "$0 7272" -> "$0.7272")
    text = re.sub(r"\$([0-9])\s+([0-9]{3,})\b", r"$\1.\2", text)

    # Strip plain raw urls (http://... or https://...)
    text = re.sub(r"https?://\S+", "", text)

    # Remove thousand separators in numbers e.g. 63,100 -> 63100, 2,440 -> 2440, 78,980 -> 78980
    while re.search(r"\b(\d{1,3}),(\d{3})\b", text):
        text = re.sub(r"\b(\d{1,3}),(\d{3})\b", r"\1\2", text)

    # Normalize multiple consecutive spaces on the same line (preserve newlines)
    lines = text.split("\n")
    cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    
    return "\n".join(cleaned_lines).strip()

