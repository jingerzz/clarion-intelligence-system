"""On-disk format for indexed filings.

Layout:
    {root}/{TICKER}/{accession}.raw.html.gz       raw filing
    {root}/{TICKER}/{accession}.tree.json.gz      indexed tree
    {root}/{TICKER}/{accession}.meta.json         metadata (small, for listing)

Trees are gzipped JSON. Metadata is unzipped so listing operations don't have
to decompress every file.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ai_buffett_zo._paths import clarion_home
from ai_buffett_zo.secrag.loader import FilingMetadata
from ai_buffett_zo.secrag.tree import ChunkNode, FilingTree, SectionNode

DEFAULT_SEC_ROOT = clarion_home() / "sec"


def save_raw(root: Path, metadata: FilingMetadata, html: str) -> Path:
    """Write the raw filing HTML to {root}/{TICKER}/{accession}.raw.html.gz."""
    path = _raw_path(root, metadata.ticker, metadata.accession)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(html.encode("utf-8")))
    return path


def load_raw(root: Path, ticker: str, accession: str) -> str:
    path = _raw_path(root, ticker, accession)
    return gzip.decompress(path.read_bytes()).decode("utf-8")


def save_tree(root: Path, tree: FilingTree) -> Path:
    """Write tree JSON.gz and metadata JSON. Returns the tree file path."""
    ticker = tree.metadata.ticker
    accession = tree.metadata.accession
    base = _ticker_dir(root, ticker)
    base.mkdir(parents=True, exist_ok=True)

    tree_path = _tree_path(root, ticker, accession)
    tree_path.write_bytes(
        gzip.compress(
            json.dumps(_tree_to_dict(tree), default=_json_default, indent=2).encode("utf-8")
        )
    )

    meta_path = _meta_path(root, ticker, accession)
    meta_path.write_text(
        json.dumps(_meta_to_dict(tree), default=_json_default, indent=2)
    )
    return tree_path


def load_tree(root: Path, ticker: str, accession: str) -> FilingTree:
    path = _tree_path(root, ticker, accession)
    raw = gzip.decompress(path.read_bytes()).decode("utf-8")
    return _tree_from_dict(json.loads(raw))


def list_indexed(root: Path, *, ticker: str | None = None) -> list[FilingMetadata]:
    """Return metadata for every indexed filing under root.

    Reads only the small .meta.json files — does not decompress trees.
    """
    base = _ticker_dir(root, ticker) if ticker else root
    if not base.exists():
        return []
    out: list[FilingMetadata] = []
    for meta_file in _iter_meta_files(base):
        try:
            data = json.loads(meta_file.read_text())
            out.append(_metadata_from_dict(data["metadata"]))
        except (json.JSONDecodeError, KeyError):
            continue
    out.sort(key=lambda m: (m.ticker, m.filed), reverse=True)
    return out


def is_indexed(root: Path, ticker: str, accession: str) -> bool:
    return _tree_path(root, ticker, accession).exists()


# --- path helpers -----------------------------------------------------------


def _ticker_dir(root: Path, ticker: str) -> Path:
    return root / ticker.upper()


def _raw_path(root: Path, ticker: str, accession: str) -> Path:
    return _ticker_dir(root, ticker) / f"{accession}.raw.html.gz"


def _tree_path(root: Path, ticker: str, accession: str) -> Path:
    return _ticker_dir(root, ticker) / f"{accession}.tree.json.gz"


def _meta_path(root: Path, ticker: str, accession: str) -> Path:
    return _ticker_dir(root, ticker) / f"{accession}.meta.json"


def _iter_meta_files(base: Path) -> Iterator[Path]:
    if base.is_dir():
        yield from base.rglob("*.meta.json")


# --- (de)serialization ------------------------------------------------------


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(f"can't serialize {type(o)}")


def _tree_to_dict(tree: FilingTree) -> dict[str, Any]:
    return {
        "metadata": asdict(tree.metadata),
        "sections": [_section_to_dict(s) for s in tree.sections],
        "indexed_at": tree.indexed_at,
        "indexer_model": tree.indexer_model,
    }


def _section_to_dict(s: SectionNode) -> dict[str, Any]:
    return {
        "label": s.label,
        "title": s.title,
        "text": s.text,
        "summary": s.summary,
        "summary_data": s.summary_data,
        "chunks": [asdict(c) for c in s.chunks],
        "is_pointer_only": s.is_pointer_only,
        "pointer_target": s.pointer_target,
    }


def _meta_to_dict(tree: FilingTree) -> dict[str, Any]:
    return {
        "metadata": asdict(tree.metadata),
        "indexed_at": tree.indexed_at,
        "indexer_model": tree.indexer_model,
        "section_labels": [s.label for s in tree.sections],
    }


def _tree_from_dict(data: dict[str, Any]) -> FilingTree:
    metadata = _metadata_from_dict(data["metadata"])
    sections = [_section_from_dict(s) for s in data["sections"]]
    return FilingTree(
        metadata=metadata,
        sections=sections,
        indexed_at=_parse_datetime(data["indexed_at"]),
        indexer_model=data["indexer_model"],
    )


def _section_from_dict(d: dict[str, Any]) -> SectionNode:
    return SectionNode(
        label=d["label"],
        title=d["title"],
        text=d["text"],
        summary=d["summary"],
        summary_data=d.get("summary_data", {}),
        chunks=[_chunk_from_dict(c) for c in d.get("chunks", [])],
        # Older indexed trees (pre-PR #26 fix) don't have these fields — default
        # to "substantive" so legacy data continues to behave as before.
        is_pointer_only=d.get("is_pointer_only", False),
        pointer_target=d.get("pointer_target"),
    )


def _chunk_from_dict(d: dict[str, Any]) -> ChunkNode:
    return ChunkNode(
        chunk_index=d["chunk_index"],
        text=d["text"],
        summary=d["summary"],
        summary_data=d.get("summary_data", {}),
    )


def _metadata_from_dict(d: dict[str, Any]) -> FilingMetadata:
    return FilingMetadata(
        cik=d["cik"],
        ticker=d["ticker"],
        company=d["company"],
        form=d["form"],
        filed=date.fromisoformat(d["filed"]),
        period=date.fromisoformat(d["period"]),
        accession=d["accession"],
        primary_doc=d["primary_doc"],
        primary_doc_url=d["primary_doc_url"],
    )


def _parse_datetime(s: Any) -> datetime:
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(str(s)).replace(tzinfo=UTC) if "T" in str(s) else datetime.now(UTC)
