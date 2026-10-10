"""Length-preserving PII masking for text sent to external model providers."""
import re


PATTERNS = (
    re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I),
    re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .()-]*\d){8,10}(?!\d)"),
    re.compile(r"(?<!\d)\d{12}(?!\d)"),
    re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
)


def mask_pii(text):
    """Replace likely email, VN phone, national ID and card spans with blocks.

    The replacement preserves Python character offsets, so quote provenance
    can be mapped back locally without sending the original PII to the model.
    """
    if not isinstance(text, str):
        raise TypeError("Text must be a string")
    masked = list(text)
    spans = []
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < old_end and old_start < end for old_start, old_end in spans):
                continue
            spans.append((start, end))
            masked[start:end] = ["█"] * (end - start)
    spans.sort()
    return "".join(masked), spans


def contains_pii(text):
    return any(pattern.search(text) for pattern in PATTERNS)
