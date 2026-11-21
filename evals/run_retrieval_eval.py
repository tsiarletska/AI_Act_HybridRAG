"""Deterministic retrieval eval (no LLM calls).

Metrics per configuration: recall@1/3/5/8 (any gold in top-k), MRR@8.
Configurations compared: see CONFIGS (ablation, each component added in turn).

usage: uv run --env-file .env python -m evals.run_retrieval_eval [--embedder local|gemini1|gemini2] [--cases ...] [--out ...]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.retrieval.search import Retriever

KS = (1, 3, 5, 8)


def matches(chunk, gold: list[str]) -> bool:
    return any(chunk.id == g or chunk.id.startswith(g + "_") or chunk.parent == g for g in gold)


CONFIGS = [
    # name, description
    ("bm25", "BM25 only"),
    ("dense", "Dense embeddings only"),
    ("hybrid", "BM25 + dense, RRF"),
    ("+glossary", "hybrid + lay→legal glossary for BM25"),
    ("+titles", "hybrid + glossary + article-title ranker (tested, not used: no gain)"),
    ("product", "hybrid + glossary + reference resolver (what the app uses)"),
]


def rank_lists(r: Retriever, q: str, k: int = max(KS)) -> dict[str, list[int]]:
    """Ranked chunk indices for each ablation configuration."""
    idx = {c.id: i for i, c in enumerate(r.chunks)}
    plain = r.rankings(q, glossary=False, titles=False)

    def ids(**flags):
        return [idx[h.id] for h in r.search(q, k=k, **flags)]

    return {
        "bm25": plain["bm25"][:k],
        "dense": plain["dense"][:k],
        "hybrid": ids(use_resolver=False, glossary=False, titles=False),
        "+glossary": ids(use_resolver=False, glossary=True, titles=False),
        "+titles": ids(use_resolver=False, glossary=True, titles=True),
        "product": ids(),
    }


def evaluate(cases_path: str = "evals/retrieval_cases.yaml", embedder: str = "local") -> dict:
    cases = yaml.safe_load(Path(cases_path).read_text())
    r = Retriever(embedder=embedder)
    configs = [c for c, _ in CONFIGS]
    agg = {c: {f"recall@{k}": 0.0 for k in KS} | {"mrr": 0.0} for c in configs}
    rows = []
    t0 = time.perf_counter()
    for case in cases:
        lists = rank_lists(r, case["q"])
        row = {"id": case["id"], "style": case["style"], "q": case["q"], "gold": case["gold"]}
        for cfg, lst in lists.items():
            first = next((n for n, i in enumerate(lst[: max(KS)], 1) if matches(r.chunks[i], case["gold"])), None)
            for k in KS:
                agg[cfg][f"recall@{k}"] += 1 if first and first <= k else 0
            agg[cfg]["mrr"] += 1 / first if first else 0
            row[cfg] = {"first_hit_rank": first, "top3": [r.chunks[i].id for i in lst[:3]]}
        rows.append(row)
    n = len(cases)
    for cfg in configs:
        for key in agg[cfg]:
            agg[cfg][key] = round(agg[cfg][key] / n, 3)
    by_style = {}
    for style in sorted({c["style"] for c in cases}):
        sub = [row for row in rows if row["style"] == style]
        hit5 = sum(1 for row in sub if (row["product"]["first_hit_rank"] or 99) <= 5)
        by_style[style] = {"n": len(sub), "recall@5": round(hit5 / len(sub), 3)}
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""
    return {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "embedder": embedder,
        "embed_api_calls": getattr(r.embedder, "calls", 0),
        "n_cases": n,
        "n_chunks": len(r.chunks),
        "seconds": round(time.perf_counter() - t0, 2),
        "metrics": agg,
        "configs": dict(CONFIGS),
        "product_by_style": by_style,
        "failures": [
            {"id": row["id"], "q": row["q"], "gold": row["gold"], "got_top3": row["product"]["top3"]}
            for row in rows
            if (row["product"]["first_hit_rank"] or 99) > 5
        ],
        "cases": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="evals/retrieval_cases.yaml")
    ap.add_argument("--embedder", default="local")
    ap.add_argument("--out")
    ap.add_argument("--show-failures", action="store_true", help="never use on the frozen test set while tuning")
    args = ap.parse_args()
    res = evaluate(args.cases, args.embedder)
    split = "test" if "test" in args.cases else "dev"
    args.out = args.out or f"evals/results/retrieval_{split}_{args.embedder}.json"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"[{args.embedder}] {res['n_cases']} cases, {res['n_chunks']} chunks, {res['seconds']}s")
    print(f"{'config':18}" + "".join(f"{k:>11}" for k in res["metrics"]["bm25"]))
    for cfg, m in res["metrics"].items():
        print(f"{cfg:18}" + "".join(f"{v:>11.3f}" for v in m.values()))
    print("by style:", res["product_by_style"])
    for f in res["failures"] if args.show_failures else []:
        print(f"  MISS {f['id']}: {f['q']}\n       gold={f['gold']} got={f['got_top3']}")


if __name__ == "__main__":
    main()
