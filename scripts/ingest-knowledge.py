"""
SONIA Knowledge Ingestion CLI (v3.0)

Bulk-loads documents into memory-engine for Sonia to reference.
Supports: plain text, markdown, PDF.

Usage:
    python ingest-knowledge.py --source /path/to/file.pdf
    python ingest-knowledge.py --source /path/to/dir --type md
    python ingest-knowledge.py --source /path/to/file.txt --tag project_docs
    python ingest-knowledge.py --list             # list ingested docs
    python ingest-knowledge.py --stats             # show ingestion stats

Chunks documents by paragraph with configurable overlap,
stores each chunk in memory-engine via the /store API,
and tracks provenance (source file, offsets, chunk index).
"""

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Add memory-engine to path for chunker reuse
sys.path.insert(0, r"S:\services\memory-engine")

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

class Config:
    memory_url = "http://127.0.0.1:7020"

DEFAULT_CHUNK_SIZE = 800   # characters (~200 tokens)
DEFAULT_OVERLAP = 100      # characters
STORE_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# Document readers
# ---------------------------------------------------------------------------

def read_text_file(path: Path) -> str:
    """Read a plain text or markdown file."""
    return path.read_text(encoding="utf-8", errors="replace")


def read_pdf_file(path: Path) -> str:
    """Read a PDF file. Requires PyMuPDF (fitz) or pdfplumber."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        pass

    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n\n".join(pages)
    except ImportError:
        pass

    print(f"ERROR: No PDF reader available. Install PyMuPDF: pip install PyMuPDF")
    print(f"  Or pdfplumber: pip install pdfplumber")
    sys.exit(1)


READERS = {
    ".txt": read_text_file,
    ".md": read_text_file,
    ".markdown": read_text_file,
    ".rst": read_text_file,
    ".pdf": read_pdf_file,
}


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_by_paragraphs(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
                        overlap: int = DEFAULT_OVERLAP) -> List[Tuple[str, int, int]]:
    """
    Chunk text by paragraph boundaries with overlap.
    Returns list of (chunk_text, start_offset, end_offset).
    """
    paragraphs = text.split("\n\n")
    chunks: List[Tuple[str, int, int]] = []
    current_parts: List[str] = []
    current_len = 0
    current_start = 0
    offset = 0

    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            offset += 2  # account for \n\n
            continue

        para_len = len(para)

        if current_len + para_len > chunk_size and current_parts:
            # Emit current chunk
            chunk_text = "\n\n".join(current_parts)
            chunks.append((chunk_text, current_start, current_start + len(chunk_text)))

            # Overlap: keep last paragraph if it fits
            if overlap > 0 and current_parts:
                last = current_parts[-1]
                if len(last) <= overlap:
                    current_parts = [last, para]
                    current_len = len(last) + para_len + 2
                    current_start = offset - len(last) - 2
                else:
                    current_parts = [para]
                    current_len = para_len
                    current_start = offset
            else:
                current_parts = [para]
                current_len = para_len
                current_start = offset
        else:
            if not current_parts:
                current_start = offset
            current_parts.append(para)
            current_len += para_len + 2

        offset += para_len + 2

    # Emit remaining
    if current_parts:
        chunk_text = "\n\n".join(current_parts)
        chunks.append((chunk_text, current_start, current_start + len(chunk_text)))

    return chunks


# ---------------------------------------------------------------------------
# Memory-engine client
# ---------------------------------------------------------------------------

def store_chunk(client: httpx.Client, chunk_text: str, metadata: Dict[str, Any]) -> Optional[str]:
    """Store a chunk in memory-engine. Returns memory_id or None on failure."""
    try:
        resp = client.post(
            f"{Config.memory_url}/store",
            json={
                "type": "fact",
                "content": chunk_text,
                "metadata": metadata,
            },
            timeout=STORE_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("id")
        else:
            print(f"  WARN: store returned {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"  WARN: store failed: {e}")
        return None


def check_memory_engine(client: httpx.Client, url: str = "") -> bool:
    """Check if memory-engine is reachable."""
    base = url or Config.memory_url
    try:
        resp = client.get(f"{base}/healthz", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Ingest pipeline
# ---------------------------------------------------------------------------

def ingest_file(
    path: Path,
    client: httpx.Client,
    tag: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Ingest a single file into memory-engine.
    Returns stats dict.
    """
    ext = path.suffix.lower()
    reader = READERS.get(ext)
    if not reader:
        return {"file": str(path), "status": "skipped", "reason": f"unsupported extension: {ext}"}

    print(f"  Reading: {path.name} ({path.stat().st_size:,} bytes)")
    text = reader(path)
    if not text.strip():
        return {"file": str(path), "status": "skipped", "reason": "empty file"}

    # Compute file hash for dedup
    file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    doc_id = f"doc_{file_hash}"

    # Chunk
    chunks = chunk_by_paragraphs(text, chunk_size=chunk_size, overlap=overlap)
    print(f"  Chunked into {len(chunks)} chunks (size={chunk_size}, overlap={overlap})")

    if dry_run:
        return {
            "file": str(path),
            "status": "dry_run",
            "doc_id": doc_id,
            "chunks": len(chunks),
            "total_chars": len(text),
        }

    # Store chunks
    stored = 0
    failed = 0
    memory_ids = []

    for i, (chunk_text, start, end) in enumerate(chunks):
        if not chunk_text.strip():
            continue

        metadata = {
            "source_type": "document_chunk",
            "doc_id": doc_id,
            "source_file": path.name,
            "source_path": str(path),
            "chunk_index": i,
            "chunk_total": len(chunks),
            "start_offset": start,
            "end_offset": end,
            "file_hash": file_hash,
            "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if tag:
            metadata["tag"] = tag

        mem_id = store_chunk(client, chunk_text, metadata)
        if mem_id:
            stored += 1
            memory_ids.append(mem_id)
        else:
            failed += 1

    return {
        "file": str(path),
        "status": "ok" if failed == 0 else "partial",
        "doc_id": doc_id,
        "chunks_total": len(chunks),
        "chunks_stored": stored,
        "chunks_failed": failed,
        "total_chars": len(text),
        "memory_ids": memory_ids[:5],  # first 5 for reference
    }


def ingest_directory(
    dir_path: Path,
    client: httpx.Client,
    file_type: str = "",
    tag: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Ingest all supported files in a directory."""
    results = []
    patterns = [f"*.{file_type}"] if file_type else ["*.txt", "*.md", "*.pdf", "*.markdown", "*.rst"]

    files = []
    for pattern in patterns:
        files.extend(dir_path.glob(pattern))
    files.sort()

    if not files:
        print(f"  No matching files found in {dir_path}")
        return results

    print(f"  Found {len(files)} files to ingest")
    for f in files:
        result = ingest_file(f, client, tag=tag, chunk_size=chunk_size,
                             overlap=overlap, dry_run=dry_run)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# List & stats commands
# ---------------------------------------------------------------------------

def list_ingested(client: httpx.Client):
    """List ingested documents by querying memory-engine."""
    try:
        resp = client.post(
            f"{Config.memory_url}/search",
            json={"query": "document_chunk", "limit": 200},
            timeout=10.0,
        )
        if resp.status_code != 200:
            print(f"Search failed: {resp.status_code}")
            return

        data = resp.json()
        results = data.get("results", [])

        # Group by doc_id
        docs: Dict[str, Dict[str, Any]] = {}
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            doc_id = meta.get("doc_id", "unknown")
            if doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "source_file": meta.get("source_file", "?"),
                    "tag": meta.get("tag", ""),
                    "chunk_count": 0,
                    "ingested_at": meta.get("ingested_at", "?"),
                }
            docs[doc_id]["chunk_count"] += 1

        if not docs:
            print("No ingested documents found.")
            return

        print(f"\nIngested documents ({len(docs)}):")
        print(f"{'Doc ID':<20} {'File':<30} {'Chunks':<8} {'Tag':<15} {'Ingested'}")
        print("-" * 90)
        for d in sorted(docs.values(), key=lambda x: x.get("ingested_at", "")):
            print(f"{d['doc_id']:<20} {d['source_file']:<30} {d['chunk_count']:<8} {d.get('tag', ''):<15} {d['ingested_at']}")

    except Exception as e:
        print(f"Error listing documents: {e}")


def show_stats(client: httpx.Client):
    """Show memory-engine statistics."""
    try:
        resp = client.get(f"{Config.memory_url}/query/stats", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            print(f"\nMemory Engine Statistics:")
            print(f"  Total memories: {data.get('total_memories', '?')}")
            print(f"  Active memories: {data.get('active_memories', '?')}")
            by_type = data.get("by_type", {})
            if by_type:
                print(f"  By type:")
                for t, c in by_type.items():
                    print(f"    {t}: {c}")
            hybrid = data.get("hybrid_search", {})
            if hybrid:
                print(f"  Hybrid search:")
                print(f"    Initialized: {hybrid.get('initialized', '?')}")
                bm25 = hybrid.get("bm25_stats", {})
                if bm25:
                    print(f"    BM25 docs: {bm25.get('num_documents', '?')}")
                    print(f"    BM25 tokens: {bm25.get('unique_tokens', '?')}")
        else:
            print(f"Stats request failed: {resp.status_code}")
    except Exception as e:
        print(f"Error getting stats: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SONIA Knowledge Ingestion CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest-knowledge.py --source doc.pdf
  python ingest-knowledge.py --source ./docs --type md --tag project
  python ingest-knowledge.py --source README.md --dry-run
  python ingest-knowledge.py --list
  python ingest-knowledge.py --stats
        """,
    )
    parser.add_argument("--source", type=str, help="File or directory to ingest")
    parser.add_argument("--type", type=str, default="", help="File extension filter (e.g., md, txt, pdf)")
    parser.add_argument("--tag", type=str, default="", help="Tag for grouping ingested content")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help=f"Chunk size in chars (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP, help=f"Overlap in chars (default: {DEFAULT_OVERLAP})")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested without storing")
    parser.add_argument("--list", action="store_true", help="List ingested documents")
    parser.add_argument("--stats", action="store_true", help="Show memory-engine statistics")
    parser.add_argument("--memory-url", type=str, default=Config.memory_url, help="Memory-engine URL")

    parsed_args = parser.parse_args()
    Config.memory_url = parsed_args.memory_url

    client = httpx.Client(timeout=STORE_TIMEOUT)

    # Check connectivity
    if not parsed_args.dry_run:
        if not check_memory_engine(client):
            print(f"ERROR: Memory-engine not reachable at {Config.memory_url}")
            print("  Start the service first: .\\start-sonia-stack.ps1")
            sys.exit(1)

    if parsed_args.list:
        list_ingested(client)
        return

    if parsed_args.stats:
        show_stats(client)
        return

    if not parsed_args.source:
        parser.print_help()
        return

    source = Path(parsed_args.source)
    if not source.exists():
        print(f"ERROR: Source not found: {source}")
        sys.exit(1)

    print("=" * 60)
    print("SONIA Knowledge Ingestion")
    print("=" * 60)
    print(f"Source: {source}")
    print(f"Chunk size: {parsed_args.chunk_size} chars, overlap: {parsed_args.overlap}")
    if parsed_args.tag:
        print(f"Tag: {parsed_args.tag}")
    if parsed_args.dry_run:
        print("Mode: DRY RUN (no data stored)")
    print()

    t0 = time.time()

    if source.is_file():
        result = ingest_file(
            source, client,
            tag=parsed_args.tag,
            chunk_size=parsed_args.chunk_size,
            overlap=parsed_args.overlap,
            dry_run=parsed_args.dry_run,
        )
        results = [result]
    elif source.is_dir():
        results = ingest_directory(
            source, client,
            file_type=parsed_args.type,
            tag=parsed_args.tag,
            chunk_size=parsed_args.chunk_size,
            overlap=parsed_args.overlap,
            dry_run=parsed_args.dry_run,
        )
    else:
        print(f"ERROR: {source} is neither a file nor directory")
        sys.exit(1)

    elapsed = time.time() - t0

    # Summary
    print()
    print("-" * 60)
    print("Ingestion Summary")
    print("-" * 60)
    total_chunks = sum(r.get("chunks_stored", r.get("chunks", 0)) for r in results)
    total_chars = sum(r.get("total_chars", 0) for r in results)
    ok_count = sum(1 for r in results if r.get("status") in ("ok", "dry_run"))
    skip_count = sum(1 for r in results if r.get("status") == "skipped")
    fail_count = sum(1 for r in results if r.get("status") == "partial")

    print(f"Files processed: {len(results)} ({ok_count} ok, {skip_count} skipped, {fail_count} partial)")
    print(f"Chunks stored: {total_chunks}")
    print(f"Total characters: {total_chars:,}")
    print(f"Time: {elapsed:.1f}s")

    for r in results:
        status = r.get("status", "?")
        fname = Path(r.get("file", "?")).name
        chunks = r.get("chunks_stored", r.get("chunks", 0))
        print(f"  [{status.upper()}] {fname} -- {chunks} chunks")

    print()
    client.close()


if __name__ == "__main__":
    main()
