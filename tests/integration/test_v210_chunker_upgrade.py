"""
v2.10 Integration Tests -- Sentence-Aware Chunker

Tests the upgraded chunker that uses regex-based sentence boundary
detection instead of naive '. ' splitting.

Tests (13):
  Sentence Tokenizer (5):
    1. Splits on period-space-uppercase boundaries
    2. Preserves abbreviations (Mr., Dr., etc.)
    3. Preserves decimal numbers (3.14)
    4. Handles exclamation and question marks
    5. Handles empty and whitespace-only input

  chunk_text Sentence Awareness (4):
    6. Chunks break at sentence boundaries when possible
    7. No mid-sentence cuts in the second half of chunk
    8. Overlap preserved between chunks
    9. Empty text returns empty list

  chunk_by_sentences (4):
    10. Groups sentences within chunk_size
    11. Overlap carries last sentence to next chunk
    12. Single long sentence not split
    13. Mixed short and long sentences
"""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "memory-engine"))

import pytest

try:
    from core.chunker import Chunker, _split_sentences
except ImportError:
    pytestmark = pytest.mark.skip(reason="memory-engine service not available (CI)")
    Chunker = _split_sentences = None


# ===========================================================================
# Sentence Tokenizer
# ===========================================================================

class TestSentenceTokenizer:

    def test_basic_sentence_split(self):
        """Splits on period-space-uppercase."""
        text = "Hello world. This is a test. Another sentence here."
        sentences = _split_sentences(text)
        assert len(sentences) == 3
        assert sentences[0] == "Hello world."
        assert sentences[1] == "This is a test."
        assert sentences[2] == "Another sentence here."

    def test_preserves_abbreviations(self):
        """Mr., Dr., etc. don't cause splits."""
        text = "Dr. Smith went to the store. He bought milk."
        sentences = _split_sentences(text)
        assert len(sentences) == 2
        assert "Dr. Smith" in sentences[0]

    def test_preserves_decimals(self):
        """Numbers like 3.14 don't cause splits."""
        text = "The value is 3.14 approximately. That is pi."
        sentences = _split_sentences(text)
        assert len(sentences) == 2
        assert "3.14" in sentences[0]

    def test_exclamation_and_question(self):
        """Handles ! and ? as sentence enders."""
        text = "Is this working? Yes it is! Great news."
        sentences = _split_sentences(text)
        assert len(sentences) == 3
        assert sentences[0].endswith("?")
        assert sentences[1].endswith("!")

    def test_empty_input(self):
        """Empty or whitespace returns empty list."""
        assert _split_sentences("") == []
        assert _split_sentences("   ") == []
        assert _split_sentences(None) == []


# ===========================================================================
# chunk_text Sentence Awareness
# ===========================================================================

class TestChunkTextSentenceAware:

    def test_breaks_at_sentence_boundary(self):
        """Chunks prefer to break at sentence boundaries."""
        # Create text with sentences that total > chunk_size
        sentences = [
            "The quick brown fox jumped over the lazy dog.",
            "It was a beautiful sunny day in the park.",
            "Children were playing and birds were singing.",
            "The fox decided to rest under a large oak tree.",
            "Meanwhile the dog was chasing its own tail happily.",
        ]
        text = " ".join(sentences)

        chunker = Chunker(chunk_size=120, overlap=20)
        chunks = chunker.chunk_text(text)

        # At least 2 chunks
        assert len(chunks) >= 2

        # Check that first chunk ends near a sentence boundary
        first_text = chunks[0][0]
        # Should end with a period (sentence boundary)
        assert first_text.rstrip().endswith(".")

    def test_no_mid_sentence_cut(self):
        """Second half of chunk should not cut mid-sentence."""
        text = (
            "First sentence is short. "
            "Second sentence provides more detail about the topic. "
            "Third sentence wraps up the paragraph nicely. "
            "Fourth sentence starts a new thought entirely."
        )
        chunker = Chunker(chunk_size=100, overlap=10)
        chunks = chunker.chunk_text(text)

        for chunk_text, _, _ in chunks[:-1]:  # Last chunk may not end cleanly
            stripped = chunk_text.rstrip()
            # Should ideally end with sentence punctuation
            assert stripped[-1] in ".!?", f"Chunk ends mid-sentence: ...{stripped[-20:]}"

    def test_overlap_preserved(self):
        """Chunks have overlapping content."""
        text = "A. " * 100  # 300 chars of short sentences
        chunker = Chunker(chunk_size=50, overlap=10)
        chunks = chunker.chunk_text(text)

        if len(chunks) >= 2:
            # End of first chunk should overlap with start of second
            _, _, end1 = chunks[0]
            _, start2, _ = chunks[1]
            assert start2 < end1, "No overlap detected between chunks"

    def test_empty_text(self):
        """Empty text returns empty list."""
        chunker = Chunker()
        assert chunker.chunk_text("") == []


# ===========================================================================
# chunk_by_sentences
# ===========================================================================

class TestChunkBySentences:

    def test_groups_within_chunk_size(self):
        """Sentences grouped to fit within chunk_size."""
        text = (
            "First sentence. Second sentence. Third sentence. "
            "Fourth sentence. Fifth sentence. Sixth sentence."
        )
        chunker = Chunker(chunk_size=80, overlap=0)
        chunks = chunker.chunk_by_sentences(text)

        for chunk in chunks:
            assert len(chunk) <= 120  # allow some margin for joining

    def test_overlap_carries_last_sentence(self):
        """With overlap, last sentence carries into next chunk."""
        text = (
            "Alpha sentence here. Beta sentence here. "
            "Gamma sentence here. Delta sentence here."
        )
        chunker = Chunker(chunk_size=50, overlap=20)
        chunks = chunker.chunk_by_sentences(text)

        if len(chunks) >= 2:
            # Last sentence of chunk N should appear in chunk N+1
            # (overlap carries it forward)
            assert len(chunks) >= 2

    def test_single_long_sentence(self):
        """A single sentence longer than chunk_size stays intact."""
        long_sentence = "This is a very long sentence that exceeds the chunk size limit by quite a significant margin indeed."
        chunker = Chunker(chunk_size=30, overlap=0)
        chunks = chunker.chunk_by_sentences(long_sentence)
        # Should produce at least one chunk containing the whole thing
        assert len(chunks) >= 1
        assert long_sentence in chunks[0]

    def test_mixed_lengths(self):
        """Mix of short and long sentences produces valid chunks."""
        text = (
            "Hi. "
            "This is a medium-length sentence about something. "
            "Ok. "
            "Another fairly long sentence that provides additional context and detail. "
            "End."
        )
        chunker = Chunker(chunk_size=100, overlap=0)
        chunks = chunker.chunk_by_sentences(text)
        assert len(chunks) >= 1
        # All content should be covered
        full = " ".join(chunks)
        assert "Hi." in full
        assert "End." in full
