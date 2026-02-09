"""Document chunking strategies."""

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


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
        """
        chunks = []
        pos = 0
        
        while pos < len(text):
            end_pos = min(pos + self.chunk_size, len(text))
            chunk = text[pos:end_pos]
            chunks.append((chunk, pos, end_pos))
            
            # Move forward by chunk_size - overlap
            pos += self.chunk_size - self.overlap
        
        logger.debug(f"Chunked text into {len(chunks)} chunks")
        return chunks

    def chunk_by_sentences(self, text: str) -> List[str]:
        """Chunk by sentence boundaries."""
        # TODO: Implement sentence-aware chunking
        sentences = text.split('. ')
        chunks = []
        current_chunk = []
        current_length = 0
        
        for sentence in sentences:
            sentence_len = len(sentence)
            if current_length + sentence_len > self.chunk_size:
                if current_chunk:
                    chunks.append('. '.join(current_chunk) + '.')
                current_chunk = [sentence]
                current_length = sentence_len
            else:
                current_chunk.append(sentence)
                current_length += sentence_len + 2  # Account for '. '
        
        if current_chunk:
            chunks.append('. '.join(current_chunk) + '.')
        
        return chunks

    def chunk_by_paragraphs(self, text: str) -> List[str]:
        """Chunk by paragraph boundaries."""
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = []
        current_length = 0
        
        for para in paragraphs:
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
