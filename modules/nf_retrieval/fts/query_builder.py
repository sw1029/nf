import re


def build_query(text: str) -> str:
    # Remove punctuation/symbols, keep alphanumeric (incl. Hangul)
    safe_text = re.sub(r'[^\w\s]', ' ', text).strip()
    words = safe_text.split()
    if not words:
        return ""
    # Use OR to allow finding related content even if not all words match
    return " OR ".join(words)
