# Third-party licenses

CIS vendors a small amount of third-party MIT-licensed code. Originals and patches:

## VectifyAI/PageIndex

- **Source:** https://github.com/VectifyAI/PageIndex
- **Vendored at commit:** `f50e529` (2026-05-08)
- **Vendored files:** `lib/ai_buffett_zo/secrag/pageindex/{page_index.py, page_index_md.py, utils.py, config.yaml}`
- **License:** MIT — see [`PageIndex-LICENSE`](./PageIndex-LICENSE)
- **Why vendored vs `pip install pageindex`:** we replace the bundled `litellm` LLM client with our own `ai_buffett_zo.llm.ZoClient` (which talks to Zo Computer's `/zo/ask`). Vendoring lets us patch `utils.py` cleanly while keeping the core tree-building algorithm unchanged.

### CIS patches to vendored files

All patches are in `utils.py` and marked with `# CIS PATCH:` comments. Specifically:

- Removed top-level `import litellm`, `litellm.drop_params = True`
- Removed `from dotenv import load_dotenv; load_dotenv()` (Zo manages env vars natively)
- Lazy-imported `PyPDF2` and `pymupdf` inside the PDF functions that use them (we don't call those paths for SEC HTML/XML, so users don't need to install PDF deps)
- `count_tokens()` uses a char/4 heuristic instead of `litellm.token_counter`
- `llm_completion()` and `llm_acompletion()` route through `ai_buffett_zo.llm.ZoClient` (sync; async wrapped via `asyncio.to_thread`)
- `get_page_tokens()` calls our `count_tokens` instead of `litellm.token_counter`
- `config.yaml` model defaults overridden to Zo-style strings (e.g., `zo:openai/gpt-5.4-mini`)

`page_index.py` and `page_index_md.py` are unchanged from upstream.

To pull a newer upstream snapshot in the future: `diff` upstream's `utils.py` against ours; the patches are well-localized at the LLM and PDF call sites.
