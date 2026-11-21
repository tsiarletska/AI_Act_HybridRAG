"""Pluggable dense embedders for the hybrid retriever.

  local    BAAI/bge-small-en-v1.5 via fastembed (384-d, CPU, no API cost)
  gemini1  gemini-embedding-001  (task_type RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT, 768-d, normalised here)
  gemini2  gemini-embedding-2    (no task_type: the task goes into the text as a prefix, 768-d auto-normalised)

Facts verified against the installed google-genai SDK and the Gemini embeddings docs (2026-11-18):
- gemini-embedding-2 aggregates several parts of one request into ONE vector, so each text
  is wrapped in its own types.Content to get one vector per text;
- gemini-embedding-2 ignores task_type (tested: identical vectors); use the prefixes
  "task: question answering | query: ..." and "title: ... | text: ...";
- gemini-embedding-001 vectors below 3072-d are not unit length and must be normalised.

Every embedder returns float32 unit vectors, so cosine similarity == dot product.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache

import numpy as np

DIM = 768
BATCH = 100  # texts per embed_content request


def _title(t: str) -> str:
    """'header\nlabel' -> 'header — label'; empty parts dropped; nothing left -> 'none' (per the docs)."""
    return " — ".join(x.strip() for x in t.split("\n") if x.strip()) or "none"


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


class Embedder:
    name: str = ""
    floor: float = 0.0  # relevance floor for this embedding space (see evals/calibrate_floor.py)

    def embed_docs(self, docs: list[tuple[str, str]]) -> np.ndarray:  # [(title, text)]
        raise NotImplementedError

    def embed_query(self, query: str) -> np.ndarray:
        return self._query(query).copy()

    def _query(self, query: str) -> np.ndarray:
        raise NotImplementedError


class LocalEmbedder(Embedder):
    name = "local"
    model = "BAAI/bge-small-en-v1.5"
    floor = 0.60

    def __init__(self):
        from fastembed import TextEmbedding

        self.m = TextEmbedding(self.model)

    def embed_docs(self, docs):
        return _unit(np.array(list(self.m.passage_embed([f"{t}\n{x}" for t, x in docs]))))

    @lru_cache(maxsize=2048)  # noqa: B019 - one instance per process
    def _query(self, query):
        return _unit(np.array(list(self.m.query_embed([query]))[0]))


class GeminiEmbedder(Embedder):
    """gemini-embedding-001 (task_type) or gemini-embedding-2 (text prefixes)."""

    def __init__(self, model: str, floor: float):
        from google import genai
        from google.genai import types

        self.model, self.floor, self.types = model, floor, types
        self.name = {"gemini-embedding-001": "gemini1", "gemini-embedding-2": "gemini2"}[model]
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.calls = 0

    @property
    def v2(self) -> bool:
        return self.model == "gemini-embedding-2"

    def _embed(self, texts: list[str], task_type: str, retries: int) -> np.ndarray:
        """retries/backoff: bulk indexing waits out rate limits (4 retries, 2-16 s); the query path
        gets 1 fast retry so a failing API hands over to the BM25 fallback in about a second."""
        from google.genai import errors

        t = self.types
        cfg = t.EmbedContentConfig(output_dimensionality=DIM, **({} if self.v2 else {"task_type": task_type}))
        out = []
        for i in range(0, len(texts), BATCH):
            contents = [t.Content(parts=[t.Part(text=x)]) for x in texts[i : i + BATCH]]
            for attempt in range(retries + 1):
                try:
                    r = self.client.models.embed_content(model=self.model, contents=contents, config=cfg)
                    self.calls += 1
                    break
                except errors.APIError as e:
                    transient = e.code == 429 or (e.code or 0) >= 500
                    if not transient or attempt == retries:  # 400/401/403: fail fast
                        raise
                    time.sleep(2 ** (attempt + 1) if retries > 1 else 0.5)
            if len(r.embeddings) != len(contents):
                raise RuntimeError(f"{self.model}: {len(r.embeddings)} vectors for {len(contents)} texts")
            out += [e.values for e in r.embeddings]
        return _unit(np.array(out))

    def embed_docs(self, docs):
        if self.v2:
            return self._embed([f"title: {_title(t)} | text: {x}" for t, x in docs], "", 4)
        return self._embed([f"{t}\n{x}" for t, x in docs], "RETRIEVAL_DOCUMENT", 4)

    @lru_cache(maxsize=2048)  # noqa: B019 - one instance per process; eval re-queries the same text
    def _query(self, query):
        if self.v2:
            return self._embed([f"task: question answering | query: {query}"], "", 1)[0]
        return self._embed([query], "RETRIEVAL_QUERY", 1)[0]


# Floors are per embedding space: cosine scales differ between models. Calibrated by
# evals/calibrate_floor.py --embedder <name> (results in evals/results/relevance_floor_<name>.json).
FLOORS = {"local": 0.60, "gemini1": 0.60, "gemini2": 0.64}


def make_embedder(name: str) -> Embedder:
    if name == "local":
        return LocalEmbedder()
    model = {"gemini1": "gemini-embedding-001", "gemini2": "gemini-embedding-2"}[name]
    return GeminiEmbedder(model, FLOORS[name] or 0.0)
