# sec-indexer

Process-mode Zo Service. Background indexer for SEC EDGAR filings. Part of [Clarion Intelligence System](../../README.md).

## What it does

Watches `~/clarion/queue/` for indexing requests. For each request:

1. Resolves ticker → CIK → latest filing of the requested form (`10-K`, `10-Q`, etc.)
2. Fetches raw HTML from SEC EDGAR
3. Saves raw to `~/clarion/sec/{TICKER}/{accession}.raw.html.gz`
4. Extracts curated sections (Business / Risk Factors / MD&A / Financial Statements)
5. Builds a hierarchical tree, summarizing each section via `/zo/ask`
6. Saves the indexed tree to `~/clarion/sec/{TICKER}/{accession}.tree.json.gz`
7. Updates per-ticker status at `~/clarion/sec/{TICKER}/.status.json`

Idempotent: filings already on disk (by accession number) are skipped.

## Configuration

Reads from environment:

| Variable          | Required | Default                                                  | Purpose                                                    |
|-------------------|----------|----------------------------------------------------------|------------------------------------------------------------|
| `ZO_API_KEY`      | Yes      | —                                                        | Zo bearer for `/zo/ask`. Generate in Settings → Advanced.   |
| `SEC_USER_AGENT`  | No       | `Clarion Intelligence System (clarion@example.com)`      | SEC requires identifying UA. Override with your contact.    |

`ZO_API_KEY` is **not** an external provider key. It's a Zo-issued bearer that authenticates this service as you, so calls are billed against your Zo monthly credits.

## Registration

The `clarion-setup` skill registers this service for you on first run. Manual equivalent — call `register_user_service` (Zo chat agent tool) with these exact parameters:

| Param | Value |
|---|---|
| `label` | `sec-indexer` |
| `mode` | `process` |
| `entrypoint` | `sec-indexer` |
| `workdir` | `/home/workspace` |
| `env_vars` | `{"ZO_API_KEY": "$ZO_API_KEY"}` |
| `description` | `Clarion sec-indexer — background SEC EDGAR filing indexer` |

The `$ZO_API_KEY` syntax (shell-style) tells Zo to resolve the value from the user's secret of that name at service start. The full reference manifest is in [`service.json`](./service.json).

Validated end-to-end on 2026-05-07 — service registered cleanly, picked up an NVDA 10-K indexing job within 60 seconds of queue write, completed in ~75 seconds total using `zo:openai/gpt-5.4-mini`.

## Logs

Appended to `~/clarion/sec/.indexer.log` and to stderr (which Zo captures into the service's log stream).

## Submitting work

Skill scripts enqueue requests by writing JSON to `~/clarion/queue/`:

```python
from ai_buffett_zo.indexer import IndexRequest, enqueue

request = IndexRequest.new("NVDA", "10-K")
enqueue(request)
# Then poll TickerStatus.last_request.state for "completed" / "failed".
```

The indexer picks up new files within `poll_interval` seconds (default 5).

## Running outside Zo (dev / debug)

```bash
ZO_API_KEY=zo_sk_...  uv run sec-indexer --poll-interval 10
```

## Files written

```
~/clarion/sec/
  .indexer.log              service log
  {TICKER}/
    .status.json            ticker status
    {accession}.raw.html.gz raw filing
    {accession}.tree.json.gz indexed tree
    {accession}.meta.json   small metadata sidecar (no decompression)
~/clarion/queue/
  {id}.json                 pending requests
  .processing/{id}.json     in-flight
  .done/{id}.json           audit trail of completed requests
  .failed/{id}.json         failed requests with error info
```
