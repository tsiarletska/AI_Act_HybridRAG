"""Sweep the BM25 weight in RRF fusion per embedder, on the DEV set only (the test set stays frozen).

usage: uv run --env-file .env python -m evals.sweep_bm25_weight
"""

import json, yaml
from pathlib import Path
from app.retrieval.search import Retriever
from evals.run_retrieval_eval import matches
cases = yaml.safe_load(Path("evals/retrieval_cases.yaml").read_text())  # DEV ONLY
out = {}
for emb in ["local", "gemini1", "gemini2"]:
    r = Retriever(embedder=emb); out[emb] = {}
    for w in [0.0, 0.25, 0.5, 0.75, 1.0]:
        r.bm25_weight = w; r1 = r5 = mrr = 0
        for c in cases:
            hits = r.search(c["q"], k=8)
            first = next((n for n, h in enumerate(hits, 1) if matches(h.chunk, c["gold"])), None)
            r1 += first == 1; r5 += bool(first and first <= 5); mrr += 1/first if first else 0
        n = len(cases); out[emb][w] = {"recall@1": round(r1/n,3), "recall@5": round(r5/n,3), "mrr": round(mrr/n,3)}
        print(emb, w, out[emb][w])
Path("evals/results/bm25_weight_sweep.json").write_text(json.dumps({"split": "dev", "config": "product", "sweep": out}, indent=2))
