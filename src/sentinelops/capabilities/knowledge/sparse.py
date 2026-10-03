"""
Sparse Lexical Scoring and Representation for Knowledge Retrieval.

Provides lightweight BM25 keyword matching and sparse vector computation
for hybrid search pipelines.
"""
from __future__ import annotations

import math
import re
from collections import Counter


class BM25Encoder:
    """
    Lightweight BM25 term frequency encoder and scorer.

    Parameters:
        k1: Term frequency saturation parameter (default 1.5).
        b: Document length normalization parameter (default 0.75).
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._doc_count = 0
        self._avg_doc_len = 1.0
        self._doc_freqs: Counter[str] = Counter()

    def tokenize(self, text: str) -> list[str]:
        """Normalize and tokenize text into lowercase words."""
        clean = re.sub(r"[^\w\s]", " ", text.lower())
        return [t for t in clean.split() if len(t) > 1]

    def fit(self, documents: list[str]) -> None:
        """Fit vocabulary and document frequency stats over a corpus."""
        self._doc_count = len(documents)
        total_len = 0
        self._doc_freqs = Counter()

        for doc in documents:
            tokens = self.tokenize(doc)
            total_len += len(tokens)
            unique_tokens = set(tokens)
            for t in unique_tokens:
                self._doc_freqs[t] += 1

        self._avg_doc_len = max(1.0, total_len / max(1, self._doc_count))

    def score(self, query: str, document: str) -> float:
        """
        Compute BM25 similarity score between query and document.
        """
        q_tokens = self.tokenize(query)
        d_tokens = self.tokenize(document)
        d_len = len(d_tokens)
        if not q_tokens or not d_tokens:
            return 0.0

        d_counts = Counter(d_tokens)
        score = 0.0

        for t in q_tokens:
            if t not in d_counts:
                continue
            tf = d_counts[t]
            df = self._doc_freqs.get(t, 1)
            # Standard Lucene/BM25 IDF
            idf = math.log(1.0 + (self._doc_count - df + 0.5) / (df + 0.5))
            numerator = tf * (self.k1 + 1.0)
            denominator = tf + self.k1 * (1.0 - self.b + self.b * (d_len / self._avg_doc_len))
            score += max(0.0, idf * (numerator / denominator))

        return score
