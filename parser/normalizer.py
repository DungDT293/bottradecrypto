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
        "\u200b", "\u200c", "\u200d", "\ufeff", "\u200e", "\u200f",
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
    text = re.sub(r"(\*\*+|__+)", " ", text)

    # Strip plain raw urls (http://... or https://...)
    text = re.sub(r"https?://\S+", "", text)

    # Normalize multiple consecutive spaces on the same line (preserve newlines)
    lines = text.split("\n")
    cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    
    return "\n".join(cleaned_lines).strip()

