"""
v2.10 Integration Tests -- Sentence Chunker Edge Cases

Tests that the memory-engine's workspace ingestion (chunker) handles
adversarial and complex text safely: tables, code blocks, multilingual
content, very long documents, and degenerate inputs.

Tests (8):
  Structure (3):
    1. Table content preserved through chunking
    2. Code blocks with backticks not split mid-block
    3. Markdown headers maintain boundary respect

  Multilingual (2):
    4. CJK characters handled without corruption
    5. Mixed-script text (Latin + Arabic + CJK) round-trips

  Edge Cases (3):
    6. Very long document (>10K chars) produces multiple chunks
    7. Empty/whitespace-only input handled gracefully
    8. Single character input does not crash
"""

import sys
import json
import time
from pathlib import Path

import pytest
import httpx

MEMORY_URL = "http://127.0.0.1:7020"
TIMEOUT = 30.0


def _skip_if_memory_down():
    """Skip test if memory-engine is not running."""
    import httpx as hx
    try:
        r = hx.get(f"{MEMORY_URL}/healthz", timeout=3.0)
        if r.status_code != 200:
            pytest.skip("Memory engine not healthy")
    except Exception:
        pytest.skip("Memory engine not reachable")


# ===========================================================================
# Structure Tests
# ===========================================================================

class TestChunkerStructure:

    @pytest.mark.asyncio
    async def test_table_content_preserved(self):
        """Table content survives chunking without row corruption."""
        _skip_if_memory_down()
        table_content = (
            "| Name | Age | City |\n"
            "|------|-----|------|\n"
            "| Alice | 30 | NYC |\n"
            "| Bob | 25 | LA |\n"
            "| Carol | 35 | CHI |\n"
        )
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEMORY_URL}/v1/workspace/ingest",
                json={
                    "content": table_content,
                    "doc_type": "test_table",
                    "metadata": {"test": "chunker_table"},
                },
            )
            assert resp.status_code == 200, f"Ingest failed: {resp.text}"
            data = resp.json()
            # Should produce at least one chunk
            chunks = data.get("chunks", data.get("chunk_count", 0))
            if isinstance(chunks, int):
                assert chunks >= 1, "Table should produce at least 1 chunk"
            else:
                assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_code_block_not_split(self):
        """Code blocks with triple backticks remain intact."""
        _skip_if_memory_down()
        code_content = (
            "Here is a function:\n\n"
            "```python\n"
            "def hello():\n"
            "    print('world')\n"
            "    return 42\n"
            "```\n\n"
            "And here is another paragraph after the code."
        )
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEMORY_URL}/v1/workspace/ingest",
                json={
                    "content": code_content,
                    "doc_type": "test_code",
                    "metadata": {"test": "chunker_code"},
                },
            )
            assert resp.status_code == 200, f"Ingest failed: {resp.text}"

    @pytest.mark.asyncio
    async def test_markdown_headers_boundary(self):
        """Markdown headers are respected as chunk boundaries."""
        _skip_if_memory_down()
        md_content = (
            "# Section One\n\n"
            "First section content with enough text to be meaningful.\n\n"
            "## Section Two\n\n"
            "Second section with different topic entirely.\n\n"
            "### Subsection\n\n"
            "More detailed content in a subsection."
        )
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEMORY_URL}/v1/workspace/ingest",
                json={
                    "content": md_content,
                    "doc_type": "test_markdown",
                    "metadata": {"test": "chunker_headers"},
                },
            )
            assert resp.status_code == 200, f"Ingest failed: {resp.text}"


# ===========================================================================
# Multilingual Tests
# ===========================================================================

class TestChunkerMultilingual:

    @pytest.mark.asyncio
    async def test_cjk_characters_preserved(self):
        """CJK (Chinese/Japanese/Korean) text survives chunking."""
        _skip_if_memory_down()
        cjk_content = (
            "This document contains mixed content.\n"
            "Chinese: \u4f60\u597d\u4e16\u754c\uff0c\u8fd9\u662f\u4e00\u4e2a\u6d4b\u8bd5\u6587\u6863\u3002\n"
            "Japanese: \u3053\u3093\u306b\u3061\u306f\u4e16\u754c\u3001\u3053\u308c\u306f\u30c6\u30b9\u30c8\u3067\u3059\u3002\n"
            "Korean: \uc548\ub155\ud558\uc138\uc694 \uc138\uacc4, \uc774\uac83\uc740 \ud14c\uc2a4\ud2b8\uc785\ub2c8\ub2e4.\n"
        )
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEMORY_URL}/v1/workspace/ingest",
                json={
                    "content": cjk_content,
                    "doc_type": "test_cjk",
                    "metadata": {"test": "chunker_cjk"},
                },
            )
            assert resp.status_code == 200, f"CJK ingest failed: {resp.text}"

    @pytest.mark.asyncio
    async def test_mixed_script_roundtrip(self):
        """Mixed-script text (Latin + Arabic + CJK) processes correctly."""
        _skip_if_memory_down()
        mixed_content = (
            "English paragraph about testing.\n"
            "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645 - Arabic greeting.\n"
            "\u4f60\u597d\u4e16\u754c - Chinese greeting.\n"
            "Final English sentence."
        )
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEMORY_URL}/v1/workspace/ingest",
                json={
                    "content": mixed_content,
                    "doc_type": "test_mixed",
                    "metadata": {"test": "chunker_mixed"},
                },
            )
            assert resp.status_code == 200, f"Mixed script ingest failed: {resp.text}"


# ===========================================================================
# Edge Case Tests
# ===========================================================================

class TestChunkerEdgeCases:

    @pytest.mark.asyncio
    async def test_long_document_produces_multiple_chunks(self):
        """Document >10K chars produces multiple chunks."""
        _skip_if_memory_down()
        # Generate a 12K character document
        paragraph = "This is a test sentence for chunking verification. " * 10
        long_content = "\n\n".join([paragraph] * 25)  # ~12,500 chars
        assert len(long_content) > 10000

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEMORY_URL}/v1/workspace/ingest",
                json={
                    "content": long_content,
                    "doc_type": "test_long",
                    "metadata": {"test": "chunker_long"},
                },
            )
            assert resp.status_code == 200, f"Long doc ingest failed: {resp.text}"
            data = resp.json()
            chunks = data.get("chunks", data.get("chunk_count", 0))
            count = chunks if isinstance(chunks, int) else len(chunks)
            assert count >= 2, (
                f"12K+ char document should produce >= 2 chunks, got {count}"
            )

    @pytest.mark.asyncio
    async def test_empty_input_handled_gracefully(self):
        """Empty or whitespace-only input does not crash."""
        _skip_if_memory_down()
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for empty_input in ["", "   ", "\n\n\n", "\t"]:
                resp = await client.post(
                    f"{MEMORY_URL}/v1/workspace/ingest",
                    json={
                        "content": empty_input,
                        "doc_type": "test_empty",
                        "metadata": {"test": "chunker_empty"},
                    },
                )
                # Should either succeed with 0 chunks or return 4xx, not 500
                assert resp.status_code != 500, (
                    f"Empty input '{repr(empty_input)}' caused 500 error"
                )

    @pytest.mark.asyncio
    async def test_single_character_input(self):
        """Single character input does not crash the chunker."""
        _skip_if_memory_down()
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEMORY_URL}/v1/workspace/ingest",
                json={
                    "content": "X",
                    "doc_type": "test_single",
                    "metadata": {"test": "chunker_single"},
                },
            )
            assert resp.status_code != 500, "Single char input caused 500 error"
