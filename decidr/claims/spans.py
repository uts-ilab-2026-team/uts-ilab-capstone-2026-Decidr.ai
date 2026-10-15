"""Bind model quotations back to original claim text without semantic repair."""

import re

_TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "\u00a0": " "})
_BOLD = re.compile(r"(?<![\w\\*])\*\*(?=\S)[^*]+?(?<=\S)(?<!\\)\*\*(?![\w*])")


def exact_claim_span(claim: str, quote: str) -> str | None:
    """Return an original substring, or None for missing or ambiguous typography matches.

    Exact nonempty quotations take precedence, including repeated exact text.
    Fallback permits only curly/straight quotes and nonbreaking/ordinary spaces;
    every substitution preserves length so matched offsets refer to the original.
    """
    if not quote:
        return None
    if quote in claim:
        return quote
    normalized_claim = claim.translate(_TYPOGRAPHY)
    normalized_quote = quote.translate(_TYPOGRAPHY)
    start = normalized_claim.find(normalized_quote)
    if start == -1 or normalized_claim.find(normalized_quote, start + 1) != -1:
        return None
    return claim[start : start + len(quote)]


def _presentation_text(text: str) -> tuple[str, list[int], list[int]]:
    code_spans = []
    opening = None
    for ticks in re.finditer(r"`+", text):
        if opening is None:
            opening = ticks
        elif len(ticks[0]) == len(opening[0]):
            code_spans.append((opening.start(), ticks.end()))
            opening = None
    if opening is not None:
        code_spans.append((opening.start(), len(text)))

    removed, starts, ends = set(), {}, {}
    for bold in _BOLD.finditer(text):
        start, end = bold.span()
        if any(a <= start < b or a < end <= b for a, b in code_spans):
            continue
        removed.update((start, start + 1, end - 2, end - 1))
        starts[start + 2], ends[end - 3] = start, end
    positions = [i for i in range(len(text)) if i not in removed]
    return (
        "".join(text[i] for i in positions).translate(_TYPOGRAPHY),
        [starts.get(i, i) for i in positions],
        [ends.get(i, i + 1) for i in positions],
    )


def exact_evidence_span(text: str, quote: str) -> str | None:
    """Bind a unique evidence quotation allowing typography and bounded Markdown bold.

    Only unnested paired ** markers with nonspace inner edges and no adjoining
    outer word characters are removable; escaped markers and backtick code stay literal.
    Returned text always comes from the original source, including stripped edge markers.
    """
    original = exact_claim_span(text, quote)
    if original is not None:
        return original
    # Preserve literal markup in code and HTML without attempting a Markdown parser.
    code_block = r"(?m)^(?: {4}|\t| {0,3}~~~)|</?(?:pre|code)\b"
    if re.search(code_block, text, re.IGNORECASE) or re.search(code_block, quote, re.IGNORECASE):
        return None
    normalized_text, starts, ends = _presentation_text(text)
    normalized_quote, _, _ = _presentation_text(quote)
    if not normalized_quote:
        return None
    start = normalized_text.find(normalized_quote)
    if start == -1 or normalized_text.find(normalized_quote, start + 1) != -1:
        return None
    return text[starts[start] : ends[start + len(normalized_quote) - 1]]
