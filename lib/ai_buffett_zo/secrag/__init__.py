"""SEC EDGAR RAG: fetch, index, search filings.

End-to-end pipeline:
    metadata, html = loader.fetch_filing("NVDA")
    sections        = sections.extract_sections(html)
    builder         = tree.TreeBuilder(client)
    filing_tree     = builder.build(metadata, sections)
    storage.save_tree(root, filing_tree)
    hits            = search.search("supply chain risk", root=root, tickers=["NVDA"])
"""

from ai_buffett_zo.secrag.loader import (
    DEFAULT_USER_AGENT,
    FilingMetadata,
    FilingNotFound,
    fetch_filing,
)
from ai_buffett_zo.secrag.search import (
    STOPWORDS,
    SearchHit,
    search,
)
from ai_buffett_zo.secrag.sections import (
    CURATED_SECTIONS,
    Section,
    extract_sections,
    extract_sections_from_text,
    html_to_text,
)
from ai_buffett_zo.secrag.storage import (
    DEFAULT_SEC_ROOT,
    is_indexed,
    list_indexed,
    load_raw,
    load_tree,
    save_raw,
    save_tree,
)
from ai_buffett_zo.secrag.tree import (
    DEFAULT_MAX_CHUNK_TOKENS,
    ChunkNode,
    FilingTree,
    SectionNode,
    TreeBuilder,
)

__all__ = [
    "CURATED_SECTIONS",
    "DEFAULT_MAX_CHUNK_TOKENS",
    "DEFAULT_SEC_ROOT",
    "DEFAULT_USER_AGENT",
    "ChunkNode",
    "FilingMetadata",
    "FilingNotFound",
    "FilingTree",
    "STOPWORDS",
    "SearchHit",
    "Section",
    "SectionNode",
    "TreeBuilder",
    "extract_sections",
    "extract_sections_from_text",
    "fetch_filing",
    "html_to_text",
    "is_indexed",
    "list_indexed",
    "load_raw",
    "load_tree",
    "save_raw",
    "save_tree",
    "search",
]
