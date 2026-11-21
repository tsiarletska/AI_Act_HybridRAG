from functools import lru_cache

import pytest

from app.ingest.chunker import build_chunks
from app.ingest.html_parser import parse
from app.retrieval.resolver import Resolver


@lru_cache
def resolver():
    return Resolver(build_chunks(parse("data/raw/aiact.html")))


@pytest.mark.parametrize(
    "q,first",
    [
        ("What does Article 6(2) say?", "art_6_2"),
        ("Art. 5(1)(a)", "art_5_1_a"),
        ("article 5 paragraph 1 point (c)", "art_5_1_c"),
        ("Annex III point 4", "anx_III_4"),
        ("What is listed in point 8 of Annex III?", "anx_III_8"),
        ("What does paragraph 2 of Article 6 say?", "art_6_2"),
        ("Explain recital 27", "rct_27"),
        ("What is a deployer?", "art_3_4"),
        ("Define AI system", "art_3_1"),
        ("Art. 3(49)", "art_3_49"),
    ],
)
def test_exact_references(q, first):
    hits = resolver().resolve_scored(q)
    assert hits and hits[0][0].id == first and hits[0][1] == "exact"


def test_bare_reference_in_long_question_is_scope():
    hits = resolver().resolve_scored(
        "Can an AI system listed in Annex III escape the high-risk classification if it is narrow?"
    )
    assert hits and all(s == "scope" for _, s in hits)


def test_definition_mentioned_in_passing_is_not_exact():
    hits = resolver().resolve_scored("What is the maximum fine for a provider that places an AI system on the market late?")
    assert all(s != "exact" for _, s in hits)


def test_unknown_article_ignored():
    assert resolver().resolve("Article 999") == []


def test_search_degrades_without_dense():
    """If the embedding API fails at query time, search still answers from BM25 + resolver."""
    from app.retrieval.search import Retriever

    r = Retriever(embedder="local")

    def boom(q):
        raise ConnectionError("embedding API down")

    r.dense_scores = boom
    hits = r.search("What does Article 50 require for chatbots?", k=5)
    assert hits and any(h.chunk.parent == "art_50" for h in hits)
    assert r.dense_ok is False and r.last_top_dense is None


@pytest.mark.parametrize("q", ["When do the rules for general-purpose AI models apply?",
                               "What is the deadline for high-risk obligations?",
                               "From which date do the prohibitions apply from?"])
def test_date_questions_bring_in_art_113(q):
    assert ("art_113", "scope") in [(c.id, s) for c, s in resolver().resolve_scored(q)]


@pytest.mark.parametrize("q", ["What is a deployer?", "Which AI practices are prohibited?",
                               "When can police use real-time remote biometric identification in public spaces?",
                               "What must a deployer do when a serious incident occurs?",
                               "When is a general-purpose AI model presumed to have systemic risk?"])
def test_non_date_question_has_no_art_113(q):
    assert "art_113" not in [c.id for c in resolver().resolve(q)]
