"""Compare chunking strategies for the AI Act on the same questions, retriever and budget.

Strategies (all built from the same parsed OJ HTML):
  fixed_250       sliding windows of 250 words, 40 overlap, structure-blind
  fixed_500       sliding windows of 500 words, 75 overlap, structure-blind
  recursive_350   split at line, then sentence boundaries, packed to <= 350 words, no labels
  article         one chunk per article / recital / annex (coarse structural)
  paragraph       one chunk per article paragraph (points never split; Art. 3 = one chunk)
  structural      the production chunker: paragraph -> point split > 350 words, one chunk per
                  definition, annex points/sections, header (chapter > article title) attached
  structural_nohdr  same chunks with header and label removed (does the context prefix help?)

Scoring is strategy-agnostic (gold labels are structural IDs, other strategies have no IDs):
  - a gold unit is the *own text* of a production chunk matching the gold ID (repeated lead-in
    removed); it counts as found when >= 50% of its word 5-grams are in the retrieved text;
  - retrieved text = ranked chunks taken until a word budget (500 / 1500 / 3000) is filled,
    the last one truncated. Recall at a fixed budget is the deciding metric: recall@k would
    reward big chunks (5 articles hold far more text than 5 points);
  - precision = share of retrieved 5-grams that belong to a gold unit;
  - citability (static) = share of chunks whose text lies (>= 90% of its 5-grams) inside one
    citable unit: paragraph-level (paragraph / point / definition / recital / annex point)
    or article-level.

Retrieval: gemini-embedding-2 dense only (the clean comparison) and the production hybrid
(BM25 weight 0.25 + dense, RRF) WITHOUT the reference resolver (it only works on structural
chunks; reported separately as a structural advantage). Note the home advantage of
`structural`: dev questions, glossary and BM25 weight were tuned on it, which is why dense-only
is the primary view.

usage: uv run --env-file .env python -m evals.chunking_eval [--cases evals/retrieval_cases.yaml]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
import time
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.ingest.chunker import Chunk, _article_header, load_chunks, save
from app.ingest.html_parser import ELI_URL, paragraphs, parse, segments, text_of
from app.retrieval import search as search_mod
from app.retrieval.search import Retriever
from evals.run_retrieval_eval import matches

SRC = "data/raw/aiact.html"
PROD = Path("data/processed/chunks.jsonl")
OUT_DIR = Path("data/processed/chunking")
BUDGETS = (500, 1500, 3000)
COVER = 0.5
N = 5  # shingle size (words)
POOL = 150
EMBEDDER = "gemini2"

STRATEGIES = {
    "fixed_250": "Sliding windows, 250 words, 40 overlap",
    "fixed_500": "Sliding windows, 500 words, 75 overlap",
    "recursive_350": "Recursive split (line > sentence), packed to 350 words",
    "article": "One chunk per article / recital / annex",
    "paragraph": "One chunk per article paragraph (points not split)",
    "structural": "Production: paragraph > point, definitions, annex points, + header",
    "structural_nohdr": "Production chunks without header/label",
}


# ---------------------------------------------------------------- text helpers
def toks(t: str) -> list[str]:
    return re.findall(r"\w+", t.lower())


def shingles(t: str) -> set[tuple[str, ...]]:
    w = toks(t)
    if len(w) < N:
        return {tuple(w)} if w else set()
    return {tuple(w[i : i + N]) for i in range(len(w) - N + 1)}


def wc(t: str) -> int:
    return len(t.split())


# ---------------------------------------------------------------- strategies
def _body(u, skip):
    return "\n".join(t for _, t in segments(u.element, skip_classes=skip))


ART_SKIP, ANX_SKIP = ("eli-title", "oj-ti-art"), ("oj-doc-ti",)


def canonical_blocks(doc) -> list[str]:
    """The whole Act in reading order, as a structure-blind text extractor would see it."""
    out = [f"({u.number}) " + re.sub(r"^\(\d+\)\s*", "", text_of(u.element)) for u in doc.recitals]
    chap, sect = None, None
    for u in doc.articles:
        if u.chapter != chap:
            chap, sect = u.chapter, None
            out.append(f"CHAPTER {u.chapter}\n{u.chapter_title}")
        if u.section and u.section != sect:
            sect = u.section
            out.append(f"SECTION {u.section}\n{u.section_title}")
        out.append(f"Article {u.number}\n{u.title}\n{_body(u, ART_SKIP)}")
    for u in doc.annexes:
        out.append(f"ANNEX {u.number}\n{u.title}\n{_body(u, ANX_SKIP)}")
    return out


def _window(i: int, text: str, prefix: str) -> Chunk:
    cid = f"{prefix}_{i:04d}"
    return Chunk(id=cid, kind="window", label="", text=text, header="", url="", parent=cid)


def fixed(blocks, size: int, overlap: int, prefix: str) -> list[Chunk]:
    words = "\n".join(blocks).split()
    step = size - overlap
    starts = range(0, max(len(words) - overlap, 1), step)
    return [_window(i, " ".join(words[s : s + size]), prefix) for i, s in enumerate(starts)]


def recursive(blocks, size: int = 350) -> list[Chunk]:
    pieces: list[str] = []
    for line in "\n".join(blocks).split("\n"):
        if wc(line) <= size:
            pieces.append(line)
            continue
        for sent in re.split(r"(?<=[.;:])\s+", line):
            w = sent.split()
            pieces += [" ".join(w[i : i + size]) for i in range(0, len(w), size)]
    packed, buf = [], []
    for p in pieces:
        if buf and wc("\n".join(buf)) + wc(p) > size:
            packed.append("\n".join(buf))
            buf = []
        buf.append(p)
    if buf:
        packed.append("\n".join(buf))
    return [_window(i, t, "r") for i, t in enumerate(packed)]


def article_level(doc, prod) -> list[Chunk]:
    out = [c for c in prod if c.kind == "recital"]
    for u in doc.articles:
        out.append(Chunk(id=u.id, kind="article", label=f"Art. {u.number}", text=_body(u, ART_SKIP),
                         header=_article_header(u), url=f"{ELI_URL}#{u.id}", parent=u.id,
                         article=u.number, title=u.title))
    for u in doc.annexes:
        out.append(Chunk(id=u.id, kind="annex", label=f"Annex {u.number}", text=_body(u, ANX_SKIP),
                         header=f"Annex {u.number} {u.title}".strip(), url=f"{ELI_URL}#{u.id}",
                         parent=u.id, title=u.title))
    return out


def paragraph_level(doc, prod) -> list[Chunk]:
    out = [c for c in prod if c.kind == "recital"]
    for u in doc.articles:
        base = dict(kind="article", header=_article_header(u), parent=u.id, article=u.number, title=u.title)
        paras = paragraphs(u.element)
        if not paras:
            out.append(Chunk(id=u.id, label=f"Art. {u.number}", text=_body(u, ART_SKIP),
                             url=f"{ELI_URL}#{u.id}", **base))
        for p, el in paras:
            out.append(Chunk(id=f"art_{u.number}_{p}", label=f"Art. {u.number}({p})", text=text_of(el),
                             url=f"{ELI_URL}#{el['id']}", paragraph=p, **base))
    return out + [c for c in prod if c.kind == "annex"]


def build_all(doc, prod) -> dict[str, list[Chunk]]:
    blocks = canonical_blocks(doc)
    return {
        "fixed_250": fixed(blocks, 250, 40, "f"),
        "fixed_500": fixed(blocks, 500, 75, "g"),
        "recursive_350": recursive(blocks),
        "article": article_level(doc, prod),
        "paragraph": paragraph_level(doc, prod),
        "structural": prod,
        "structural_nohdr": [replace(c, header="", label="") for c in prod],
    }


# ---------------------------------------------------------------- gold & citability
def own_texts(prod: list[Chunk]) -> dict[str, str]:
    """Production chunk text without the paragraph lead-in that point chunks repeat."""
    groups: dict[str, list[Chunk]] = defaultdict(list)
    for c in prod:
        if c.kind == "article" and c.point:
            groups[c.id.rsplit("_", 1)[0]].append(c)
    own = {c.id: c.text for c in prod}
    for sibs in groups.values():
        if len(sibs) < 2:
            continue
        lead = sibs[0].text
        for s in sibs[1:]:
            i = 0
            while i < min(len(lead), len(s.text)) and lead[i] == s.text[i]:
                i += 1
            lead = lead[:i]
        lead = lead[: lead.rfind("\n") + 1]  # body = f"{lead}\n{point}": cut at a line boundary
        for s in sibs:
            own[s.id] = s.text[len(lead) :] if lead else s.text
    return own


def citable_keys(c: Chunk) -> tuple[str, str]:
    """(paragraph-level key, article-level key) of a production chunk."""
    if c.kind in ("recital", "definition", "annex"):
        return c.id, c.parent
    return (f"{c.parent}#{c.paragraph}" if c.paragraph else c.parent), c.parent


def citability(chunks: list[Chunk], sh_keys: dict) -> dict[str, float]:
    para_ok = art_ok = 0
    for c in chunks:
        pc, ac = Counter(), Counter()
        for s in shingles(c.text):
            ks = sh_keys.get(s)
            if ks and len(ks) == 1:  # boilerplate shared by several units says nothing
                p, a = next(iter(ks))
                pc[p] += 1
                ac[a] += 1
        tot = sum(pc.values())
        if tot:
            para_ok += pc.most_common(1)[0][1] / tot >= 0.9
            art_ok += ac.most_common(1)[0][1] / tot >= 0.9
    n = len(chunks)
    return {"paragraph_level": round(para_ok / n, 3), "article_level": round(art_ok / n, 3)}


# ---------------------------------------------------------------- scoring
def take(ranked: list[Chunk], budget: int) -> list[str]:
    """Texts that fit the word budget (header + label + text count); the last one truncated."""
    used, out = 0, []
    for c in ranked:
        hdr = wc(c.header) + wc(c.label)
        w = c.text.split()
        if used + hdr + len(w) <= budget:
            out.append(c.text)
            used += hdr + len(w)
            continue
        room = budget - used - hdr
        if room > 0:
            out.append(" ".join(w[:room]))
        break
    return out


def score(texts: list[str], gold_units: list[set], gold_all: set) -> tuple[bool, float]:
    got = set().union(*(shingles(t) for t in texts)) if texts else set()
    hit = any(g and len(g & got) / len(g) >= COVER for g in gold_units)
    prec = len(got & gold_all) / len(got) if got else 0.0
    return hit, prec


def evaluate(cases_path: str) -> dict:
    doc = parse(SRC)
    prod = load_chunks(PROD)
    strategies = build_all(doc, prod)
    own = own_texts(prod)
    unit_sh = {c.id: shingles(own[c.id]) for c in prod}
    sh_keys: dict = defaultdict(set)
    for c in prod:
        k = citable_keys(c)
        for s in unit_sh[c.id]:
            sh_keys[s].add(k)

    cases = yaml.safe_load(Path(cases_path).read_text())

    # one embedder instance, query vectors computed once with patient retries, so a transient
    # API error can never silently degrade a strategy to BM25-only
    shared: dict = {}
    orig = search_mod.make_embedder
    search_mod.make_embedder = lambda name: shared.setdefault(name, orig(name))
    emb = search_mod.make_embedder(EMBEDDER)
    qvec = {}
    for case in cases:
        for attempt in range(6):
            try:
                qvec[case["q"]] = emb.embed_query(case["q"])
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
    emb.embed_query = lambda q: qvec[q].copy()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, chunks in strategies.items():
        path = PROD if name == "structural" else OUT_DIR / f"{name}.jsonl"
        if name != "structural":
            save(chunks, path)
        r = Retriever(chunks_path=path, embedder=EMBEDDER)
        words = [c.words or wc(c.text) for c in chunks]
        res = {
            "description": STRATEGIES[name],
            "n_chunks": len(chunks),
            "median_words": int(st.median(words)),
            "max_words": max(words),
            "indexed_words": sum(wc(c.index_text) for c in chunks),
            "citability": citability(chunks, sh_keys),
        }
        for mode in ("dense", "hybrid"):
            agg = {b: {"recall": 0, "precision": 0.0} for b in BUDGETS}
            agg["top5_chunks"] = {"recall": 0, "words": 0}
            per_case = []
            for case in cases:
                if mode == "dense":
                    ranked = [r.chunks[i] for i in r.rankings(case["q"], pool=POOL, titles=False)["dense"]]
                else:
                    ranked = [h.chunk for h in r.search(case["q"], k=POOL, pool=POOL, use_resolver=False)]
                assert r.dense_ok, f"dense retrieval failed for {name}"
                gold = [c for c in prod if matches(c, case["gold"])]
                gunits = [unit_sh[c.id] for c in gold]
                gall = set().union(*gunits) if gunits else set()
                row = {"id": case["id"]}
                for b in BUDGETS:
                    hit, prec = score(take(ranked, b), gunits, gall)
                    agg[b]["recall"] += hit
                    agg[b]["precision"] += prec
                    row[str(b)] = hit
                hit5, _ = score([c.text for c in ranked[:5]], gunits, gall)
                agg["top5_chunks"]["recall"] += hit5
                agg["top5_chunks"]["words"] += sum(wc(c.text) for c in ranked[:5])
                per_case.append(row)
            n = len(cases)
            res[mode] = {
                **{f"recall@{b}w": round(agg[b]["recall"] / n, 3) for b in BUDGETS},
                **{f"precision@{b}w": round(agg[b]["precision"] / n, 3) for b in BUDGETS},
                "recall@5chunks": round(agg["top5_chunks"]["recall"] / n, 3),
                "avg_words_in_top5": int(agg["top5_chunks"]["words"] / n),
            }
            res[f"{mode}_cases"] = per_case
        results[name] = res
        print(f"{name:17} chunks={len(chunks):4} dense " + " ".join(
            f"{k}={v}" for k, v in res["dense"].items() if k.startswith("recall")))
    search_mod.make_embedder = orig
    return {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": cases_path,
        "n_cases": len(cases),
        "embedder": EMBEDDER,
        "budgets_words": BUDGETS,
        "coverage_threshold": COVER,
        "shingle_words": N,
        "embed_api_calls": getattr(emb, "calls", 0),
        "strategies": results,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="evals/retrieval_cases.yaml")
    args = ap.parse_args()
    split = "test" if "test" in args.cases else "dev"
    res = evaluate(args.cases)
    out = Path(f"evals/results/chunking_{split}.json")
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    hdr = f"{'strategy':17}{'chunks':>7}{'med.w':>6}{'cite¶':>6}{'citeArt':>8} | " + " ".join(
        f"{m}@{b:<5}" for m in ("D", "H") for b in BUDGETS)
    print("\n" + hdr)
    for name, r in res["strategies"].items():
        print(f"{name:17}{r['n_chunks']:>7}{r['median_words']:>6}{r['citability']['paragraph_level']:>6.2f}"
              f"{r['citability']['article_level']:>8.2f} | " + " ".join(
                  f"{r[m][f'recall@{b}w']:<7.2f}" for m in ("dense", "hybrid") for b in BUDGETS))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
