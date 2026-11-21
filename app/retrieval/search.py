"""Hybrid retrieval: reference resolver + BM25 + dense embeddings, fused with RRF."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from app.ingest.chunker import Chunk, load_chunks

from .embedders import make_embedder
from .resolver import Resolver

log = logging.getLogger(__name__)

DEFAULT_EMBEDDER = "gemini2"  # local | gemini1 | gemini2 (env EMBEDDER overrides)
RRF_K = 60
# BM25 weight in RRF, per embedder (dense weight = 1). Tuned on the dev set only: see
# evals/results/bm25_weight_sweep.json. A weak embedder needs BM25 as an equal partner.
BM25_WEIGHT = {"local": 1.0, "gemini1": 0.25, "gemini2": 0.25}
RECITAL_WEIGHT = 0.8
# Relevance floor (refuse before any LLM call) is per embedder: see embedders.FLOORS.

_STOP = set(
    ["a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "by", "with", "as", "at", "from", "that", "this", "these", "those", "is", "are", "be", "been", "was", "were", "it", "its", "which", "what", "who", "whom", "when", "where", "how", "does", "do", "did", "can", "could", "shall", "should", "would", "will", "may", "might", "must", "not", "no", "any", "all", "under", "into", "than", "then", "there", "their", "them", "they", "i", "we", "you", "me", "my", "our", "your", "about", "please", "tell", "explain", "according", "regulation", "act", "ai", "eu"]
)


# Lay → legal vocabulary used by the Act. Applied to BM25 queries only (dense handles paraphrase).
GLOSSARY: list[tuple[str, str]] = [
    (r"\bfine[sd]?\b|\bpenalt", "fines penalties administrative"),
    (r"\b(staff|employees?|employers?|workers?)\b", "workplace"),
    (r"\bcomplain(t|ts)?\b", "lodge complaint"),
    (r"\b(start|begin|come into force|take effect|in force|applicable)\b", "apply from entry force"),
    (r"\bchat ?bots?\b", "interacting natural persons"),
    (r"\bdeep ?fakes?\b", "deep fake"),
    (r"\bwatermark", "machine-readable marked detectable"),
    (r"\bgpai\b", "general-purpose"),
    (r"\bface recognition|facial recognition\b", "facial recognition biometric"),
    (r"\bpolice|policing\b", "law enforcement"),
    (r"\b(job|hiring|recruit\w*|applicants?)\b", "recruitment selection employment"),
    (r"\b(loan|credit)\b", "creditworthiness credit score"),
    (r"\b(university|school|students?)\b", "education vocational training admission"),
    (r"\b(company|companies|business(es)?)\b", "undertaking"),
    (r"\bopen.?source\b", "free open-source licence"),
    (r"\bbanned|forbidden|illegal|not allowed\b", "prohibited prohibition"),
]


def expand(query: str) -> str:
    q = query.lower()
    extra = [terms for pat, terms in GLOSSARY if re.search(pat, q)]
    return query + (" " + " ".join(extra) if extra else "")


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for t in toks:
        if t in _STOP or len(t) < 2:
            continue
        if len(t) > 4 and t.endswith("ies"):
            t = t[:-3] + "y"
        elif len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


@dataclass
class Hit:
    chunk: Chunk
    score: float
    sources: dict[str, float] = field(default_factory=dict)  # resolver/bm25/dense ranks or scores

    @property
    def id(self) -> str:
        return self.chunk.id


class Retriever:
    def __init__(self, chunks_path: str | Path = "data/processed/chunks.jsonl", use_dense: bool = True,
                 embedder: str | None = None):
        self.chunks_path = Path(chunks_path)
        self.chunks = load_chunks(self.chunks_path)
        self.resolver = Resolver(self.chunks)
        self.bm25 = BM25Okapi([tokenize(c.index_text) for c in self.chunks])
        # title ranker: article / annex titles are short, dense summaries ("Obligations of importers")
        self.title_bm25 = BM25Okapi([tokenize(c.title if c.kind != "recital" else "") or ["_"] for c in self.chunks])
        self.use_dense = use_dense
        self.embedder_name = embedder or os.environ.get("EMBEDDER", DEFAULT_EMBEDDER)
        self.embedder = make_embedder(self.embedder_name) if use_dense else None
        self.relevance_floor = self.embedder.floor if self.embedder else 0.0
        self.bm25_weight = BM25_WEIGHT.get(self.embedder_name, 1.0)
        self.emb: np.ndarray | None = self._load_or_build_embeddings() if use_dense else None

    # ------------------------------------------------------------ dense
    def _load_or_build_embeddings(self) -> np.ndarray:
        """Chunk vectors cached per (chunks file, embedder): built once, then loaded from disk."""
        digest = hashlib.sha256(self.chunks_path.read_bytes()).hexdigest()[:16]
        cache = self.chunks_path.with_name(f"embeddings_{self.embedder_name}_{digest}.npy")
        if cache.exists():
            return np.load(cache)
        docs = [(f"{c.header}\n{c.label}", c.text) for c in self.chunks]  # local/gemini1 == index_text
        vecs = self.embedder.embed_docs(docs)
        np.save(cache, vecs)
        return vecs

    def dense_scores(self, query: str) -> np.ndarray:
        return self.emb @ self.embedder.embed_query(query)

    # ------------------------------------------------------------ search
    def _rankings(self, query: str, pool: int, glossary: bool, titles: bool):
        """Pure: (per-ranker ordered chunk indices, dense scores or None). No instance state is written,
        so concurrent requests on the shared retriever cannot see each other's results."""
        out: dict[str, list[int]] = {}
        toks = tokenize(expand(query) if glossary else query)
        bm = self.bm25.get_scores(toks)
        out["bm25"] = [int(i) for i in np.argsort(-bm)[:pool] if bm[i] > 0]
        if titles:
            ts = self.title_bm25.get_scores(toks)
            out["title"] = [int(i) for i in np.argsort(-ts)[:pool] if ts[i] > 0]
        ds = None
        if self.use_dense:
            try:
                ds = self.dense_scores(query)
            except Exception as e:  # embedding API down / quota: degrade to BM25 + resolver
                log.warning("dense retrieval unavailable (%s): BM25 + resolver only", type(e).__name__)
            else:
                out["dense"] = [int(i) for i in np.argsort(-ds)[:pool]]
        return out, ds

    def rankings(self, query: str, pool: int = 50, glossary: bool = True, titles: bool = True):
        """Per-ranker lists (used by the eval scripts). Also records dense_ok/_last_dense for them."""
        out, ds = self._rankings(query, pool, glossary, titles)
        self.dense_ok, self._last_dense = ds is not None, ds
        return out

    def fuse(self, lists: dict[str, list[int]], weights: dict[str, float] | None = None):
        weights = weights or {"bm25": self.bm25_weight, "dense": 1.0, "title": 0.5}
        fused: dict[int, float] = {}
        sources: dict[int, dict[str, float]] = {}
        for name, lst in lists.items():
            for rank, i in enumerate(lst):
                fused[i] = fused.get(i, 0) + weights.get(name, 1.0) / (RRF_K + rank + 1)
                sources.setdefault(i, {})[f"{name}_rank"] = rank + 1
        for i in fused:
            if self.chunks[i].kind == "recital":
                fused[i] *= RECITAL_WEIGHT
        return fused, sources

    def retrieve(self, query: str, k: int = 8, pool: int = 50, use_resolver: bool = True,
                 glossary: bool = True, titles: bool = False) -> tuple[list[Hit], float | None]:
        """Thread-safe search: (hits, best dense similarity or None if dense retrieval was unavailable).
        None means the relevance floor is skipped; the LLM guard still runs."""
        idx = {c.id: i for i, c in enumerate(self.chunks)}
        lists, ds = self._rankings(query, pool, glossary, titles)
        # weights are per embedder; without dense, BM25 is the only semantic ranker (weight 1)
        fused, sources = self.fuse(lists, None if ds is not None else {"bm25": 1.0, "title": 0.5})

        if use_resolver:
            resolved = self.resolver.resolve_scored(query)
            n = len(resolved)
            for pos, (c, strength) in enumerate(resolved):
                i = idx[c.id]
                sources.setdefault(i, {})["resolver"] = strength
                if strength == "exact":  # explicitly named unit: goes first, in mention order
                    fused[i] = 1.0 + (n - pos) * 1e-3
                else:  # article/annex mentioned in passing: a boost, not an override
                    fused[i] = fused.get(i, 0) + 1 / (RRF_K + 1)

        order = sorted(fused, key=lambda i: -fused[i])[:k]
        top = float(ds.max()) if ds is not None else None
        return [Hit(self.chunks[i], fused[i], sources.get(i, {})) for i in order], top

    def search(self, query: str, k: int = 8, pool: int = 50, use_resolver: bool = True,
               glossary: bool = True, titles: bool = False) -> list[Hit]:
        """retrieve() for single-threaded callers (eval scripts): also records last_top_dense / dense_ok."""
        hits, top = self.retrieve(query, k, pool, use_resolver, glossary, titles)
        self.last_top_dense, self.dense_ok = top, top is not None
        return hits

    def get(self, chunk_id: str) -> Chunk | None:
        return self.resolver.by_id.get(chunk_id)
