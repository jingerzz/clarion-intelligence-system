"""Vendored slim core of VectifyAI/PageIndex (MIT-licensed).

Source: https://github.com/VectifyAI/PageIndex @ commit f50e529 (2026-05-08).
License: MIT — see LICENSES/PageIndex-LICENSE at the repo root.

Vendored modules:
- page_index.py         — full document tree builder (unchanged from upstream)
- page_index_md.py      — markdown → tree (md_to_tree, unchanged)
- utils.py              — utilities + LLM/token helpers (PATCHED — see CIS PATCH
                           markers; LLM calls now route through
                           ai_buffett_zo.llm.ZoClient instead of litellm)
- config.yaml           — defaults overridden to use Zo-style model strings

Skipped from upstream:
- client.py / retrieve.py — we provide our own thin orchestrator (next phases)
"""

from ai_buffett_zo.secrag.pageindex.page_index import *  # noqa: F401, F403
from ai_buffett_zo.secrag.pageindex.page_index_md import md_to_tree  # noqa: F401
from ai_buffett_zo.secrag.pageindex.utils import (  # noqa: F401
    ConfigLoader,
    count_tokens,
    llm_acompletion,
    llm_completion,
)
