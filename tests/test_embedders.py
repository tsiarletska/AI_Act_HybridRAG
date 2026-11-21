"""Embedder retry policy (no network: the client is replaced by a fake)."""

import pytest
from google.genai import errors

from app.retrieval import embedders
from app.retrieval.embedders import GeminiEmbedder


class FakeModels:
    def __init__(self, code):
        self.code, self.calls = code, 0

    def embed_content(self, **_):
        self.calls += 1
        raise (errors.ClientError if self.code < 500 else errors.ServerError)(self.code, {"error": {"message": "x"}})


def make(code, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(embedders.time, "sleep", lambda s: None)
    e = GeminiEmbedder("gemini-embedding-2", 0.64)
    fake = FakeModels(code)
    e.client = type("FakeClient", (), {"models": fake})()
    return e


def test_query_fails_fast_on_client_error(monkeypatch):
    e = make(400, monkeypatch)
    with pytest.raises(errors.ClientError):
        e.embed_query("q-400")
    assert e.client.models.calls == 1  # no retry: hand over to the BM25 fallback at once


@pytest.mark.parametrize("code", [429, 503])
def test_query_retries_transient_once(code, monkeypatch):
    e = make(code, monkeypatch)
    with pytest.raises(errors.APIError):
        e.embed_query(f"q-{code}")
    assert e.client.models.calls == 2


def test_bulk_indexing_retries_longer(monkeypatch):
    e = make(429, monkeypatch)
    with pytest.raises(errors.APIError):
        e.embed_docs([("t", "x")])
    assert e.client.models.calls == 5
