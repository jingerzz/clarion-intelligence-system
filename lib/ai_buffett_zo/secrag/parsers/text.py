"""Text passthrough parser.

For raw plain-text filings (rare but supported). Normalizes whitespace and
emits a single H1 wrapper if no markdown headings are detected, so that the
generic section extractor produces at least one section.
"""

from __future__ import annotations

import re


def parse_text(content: str) -> str:
    """Normalize whitespace; if no markdown headings present, prepend a single H1."""
    text = content.strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # If the text already has markdown headings, leave it alone
    if re.search(r"^#{1,6}\s+\S", text, re.MULTILINE):
        return text
    # Otherwise, wrap with a single H1 so generic extraction gets one section
    return "# Filing content\n\n" + text
