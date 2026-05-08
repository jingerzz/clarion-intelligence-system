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
from ai_buffett_zo.secrag.parsers import (
    ContentType,
    detect_content_type,
    parse,
    parse_html,
    parse_text,
    parse_xml,
)
from ai_buffett_zo.secrag.search import (
    STOPWORDS,
    SearchHit,
    search,
)
from ai_buffett_zo.secrag.sections import (
    CURATED_FORMS,
    CURATED_SECTIONS,
    FULL_INDEX_FORMS,
    Section,
    extract_sections,
    extract_sections_for_form,
    extract_sections_from_text,
    extract_sections_generic,
    html_to_text,
    normalize_form,
    should_full_index,
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
    RAW_INDEX_TOKEN_LIMIT,
    ChunkNode,
    FilingTree,
    SectionNode,
    TreeBuilder,
    build_raw_tree,
)

__all__ = [
    "CURATED_FORMS",
    "CURATED_SECTIONS",
    "ContentType",
    "DEFAULT_MAX_CHUNK_TOKENS",
    "DEFAULT_SEC_ROOT",
    "DEFAULT_USER_AGENT",
    "FULL_INDEX_FORMS",
    "RAW_INDEX_TOKEN_LIMIT",
    "ChunkNode",
    "FilingMetadata",
    "FilingNotFound",
    "FilingTree",
    "STOPWORDS",
    "SearchHit",
    "Section",
    "SectionNode",
    "TreeBuilder",
    "build_raw_tree",
    "detect_content_type",
    "extract_sections",
    "extract_sections_for_form",
    "extract_sections_from_text",
    "extract_sections_generic",
    "fetch_filing",
    "html_to_text",
    "is_indexed",
    "list_indexed",
    "load_raw",
    "load_tree",
    "normalize_form",
    "parse",
    "parse_html",
    "parse_text",
    "parse_xml",
    "save_raw",
    "save_tree",
    "search",
    "should_full_index",
]
