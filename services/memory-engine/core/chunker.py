"""Document chunking strategies.

Provides three strategies:
  1. chunk_text       -- character-based with overlap (fast, default)
  2. chunk_by_sentences -- sentence-aware with regex tokenizer
  3. chunk_by_paragraphs -- paragraph-aware
"""

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Sentence boundary detection
# Matches: sentence-ending punctuation + whitespace + uppercase letter
# Post-filters abbreviations and decimal numbers to avoid false splits.
_SENTENCE_SPLIT = re.compile(
    r"(?<!\d)"                  # not preceded by digit (avoid 3.14)
    r"([.!?])"                  # sentence-ending punctuation
    r'(?:\s*["\'\)]*)'          # optional closing quotes/parens
    r"\s+"                      # required whitespace
    r"(?=[A-Z\"\'\(])",         # followed by uppercase or opening quote
    re.MULTILINE,
)

_ABBREV_SET = frozenset([
    "Mr", "Mrs", "Ms", "Dr", "Prof", "Sr", "Jr", "vs", "etc", "viz",
    "al", "cf", "approx", "dept", "est", "govt", "Inc", "Ltd", "Corp",
    "Co", "No", "Vol", "Rev", "Sgt", "Gen", "Pres", "Supt",
    "e.g", "i.e",
])


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using regex boundary detection.

    Returns a list of sentence strings. Each retains its trailing
    punctuation. Whitespace between sentences is stripped.

    Filters out false positives from abbreviations (Mr., Dr., etc.)
    by checking the word immediately before the split point.
    """
    if not text or not text.strip():
        return []

    # Split at sentence boundaries, keeping the delimiter
    parts = _SENTENCE_SPLIT.split(text)

    # Reassemble: every even index is text, odd index is the punctuation char
    raw_sentences: List[str] = []
    i = 0
    while i < len(parts):
        segment = parts[i]
        # Attach the punctuation back to its sentence
        if i + 1 < len(parts) and parts[i + 1] in ".!?":
            segment += parts[i + 1]
            i += 2
        else:
            i += 1
        segment = segment.strip()
        if segment:
            raw_sentences.append(segment)

    if not raw_sentences:
        return [text.strip()] if text.strip() else []

    # Post-filter: merge back false splits caused by abbreviations
    merged: List[str] = [raw_sentences[0]]
    for sent in raw_sentences[1:]:
        prev = merged[-1]
        # Extract the last word before the period in the previous sentence
        last_word = prev.rstrip(".!?").rsplit(None, 1)[-1] if prev.rstrip(".!?") else ""
        if last_word in _ABBREV_SET:
            # False split -- merge back
            merged[-1] = prev + " " + sent
        else:
            merged.append(sent)

    return merged


class Chunker:
    """Chunks documents for semantic search."""

    def __init__(self, chunk_size: int = 512, overlap: int = 64):
        """Initialize chunker with size and overlap."""
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str) -> List[Tuple[str, int, int]]:
        """
        Chunk text into overlapping chunks.
        Returns list of (chunk_text, start_offset, end_offset).

        Uses sentence-aware boundaries when possible: walks forward
        up to chunk_size characters, then backs up to the nearest
        sentence boundary to avoid mid-sentence cuts.
        """
        if not text:
            return []

        chunks = []
        pos = 0
        text_len = len(text)

        while pos < text_len:
            end_pos = min(pos + self.chunk_size, text_len)

            # If we're not at the very end, try to find a sentence
            # boundary to avoid cutting mid-sentence.
            if end_pos < text_len:
                # Look backwards from end_pos for a sentence-ending char
                # followed by whitespace (approximate boundary).
                best = end_pos
                search_start = max(pos + self.chunk_size // 2, pos)
                window = text[search_start:end_pos]
                # Find the last sentence-ending punctuation in the window
                for match in re.finditer(r'[.!?]\s', window):
                    # Position in the original text
                    candidate = search_start + match.end()
                    best = candidate
                if best > pos:
                    end_pos = best

            chunk = text[pos:end_pos]
            chunks.append((chunk.strip(), pos, end_pos))

            # Advance with overlap
            step = max(end_pos - pos - self.overlap, 1)
            pos += step

        logger.debug(f"Chunked text into {len(chunks)} chunks (sentence-aware)")
        return chunks

    def chunk_by_sentences(self, text: str) -> List[str]:
        """Chunk by sentence boundaries.

        Uses regex-based sentence tokenizer that handles common
        abbreviations, decimal numbers, and quoted sentences.
        Groups sentences into chunks that respect chunk_size.
        """
        sentences = _split_sentences(text)
        if not sentences:
            return [text] if text and text.strip() else []

        chunks = []
        current_chunk: List[str] = []
        current_length = 0

        for sentence in sentences:
            sentence_len = len(sentence)

            # If adding this sentence would exceed the limit
            if current_length + sentence_len + 1 > self.chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                # Overlap: carry last sentence into next chunk
                if self.overlap > 0 and current_chunk:
                    last = current_chunk[-1]
                    current_chunk = [last]
                    current_length = len(last)
                else:
                    current_chunk = []
                    current_length = 0

            current_chunk.append(sentence)
            current_length += sentence_len + 1  # +1 for space

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    def chunk_by_paragraphs(self, text: str) -> List[str]:
        """Chunk by paragraph boundaries."""
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            para_len = len(para)
            if current_length + para_len > self.chunk_size:
                if current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_length = para_len
            else:
                current_chunk.append(para)
                current_length += para_len + 2

        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        return chunks
