"""Structural tests for parsing/chunking the AI Act (original OJ HTML)."""

import re
from functools import lru_cache

import pytest

from app.ingest.chunker import build_chunks, extract_refs
from app.ingest.html_parser import paragraphs, parse, text_of

SRC = "data/raw/aiact.html"


@lru_cache
def doc():
    return parse(SRC)


@lru_cache
def chunks():
    return build_chunks(doc())


def by_id():
    return {c.id: c for c in chunks()}


def test_document_counts():
    d = doc()
    assert len(d.recitals) == 180
    assert len(d.articles) == 113
    assert len(d.annexes) == 13
    assert d.date == "12.7.2024"


def test_68_definitions():
    defs = [c for c in chunks() if c.kind == "definition"]
    assert len(defs) == 68
    assert by_id()["art_3_1"].term == "AI system"
    assert by_id()["art_3_4"].term == "deployer"


def test_chunk_ids_unique_and_every_unit_covered():
    cs = chunks()
    assert len({c.id for c in cs}) == len(cs)
    parents = {c.parent for c in cs}
    d = doc()
    for u in d.recitals + d.articles + d.annexes:
        assert u.id in parents, f"{u.id} has no chunk"


def test_no_article_text_lost():
    """Every word of every article paragraph appears in that article's chunks."""
    cs = chunks()
    for art in doc().articles:
        chunk_words = set(" ".join(c.text for c in cs if c.parent == art.id).split())
        for _, el in paragraphs(art.element):
            missing = set(text_of(el).split()) - chunk_words
            assert not missing, f"{art.id}: {list(missing)[:5]}"


def test_known_texts():
    b = by_id()
    assert "EUR 35 000 000" in b["art_99_3"].text and "7 %" in b["art_99_3"].text
    assert "10^25" in b["art_51_2"].text  # superscript kept
    assert "2 August 2026" in b["art_113"].text
    assert "social scor" in b["art_5_1_c"].text.lower() or "social behaviour" in b["art_5_1_c"].text
    assert b["art_5_1_a"].text.startswith("1. The following AI practices shall be prohibited")  # lead-in kept


def test_labels_and_urls():
    b = by_id()
    assert b["art_5_1_a"].label == "Art. 5(1)(a)"
    assert b["art_6_2"].label == "Art. 6(2)"
    assert b["anx_III_4"].label == "Annex III, point 4"
    assert b["rct_47"].label == "Recital 47"
    assert b["art_6_2"].url.endswith("#006.002")
    assert "Section 1" in b["art_6_2"].header


def test_chunk_size_bounded():
    big = [c.id for c in chunks() if c.kind != "recital" and c.words > 450]
    assert not big, big


@pytest.mark.parametrize(
    "text,expected",
    [
        ("referred to in Article 6(2)", ["art_6_2"]),
        ("listed in Annex III", ["anx_III"]),
        ("Articles 8 to 10", ["art_8", "art_9", "art_10"]),
    ],
)
def test_extract_refs(text, expected):
    assert all(e in extract_refs(text) for e in expected)


def test_no_footnote_markers_in_text():
    # footnote markers like "(1)" in superscript are removed; no '^(' leftovers
    assert not any(re.search(r"\^\(\d+\)", c.text) for c in chunks())


def test_references_to_other_acts_ignored():
    assert extract_refs("in Article 17 of Regulation (EU) 2018/1139") == []
    assert extract_refs("Article 4(3) of Regulation (EC) No 300/2008") == []


def test_quoted_paragraphs_of_amended_acts_not_split():
    """Articles 102-110 quote other acts' paragraphs (ids like 017.003); they must not
    become 'Art. 108(3)' chunks."""
    ids = {c.id for c in chunks() if c.parent == "art_108"}
    assert ids == {"art_108"}
