"""Experiment A (2026-11-21): should retrieval search with the user's original message or the guard's rewrite?

No LLM calls: the rewrites are the ones the guard produced in run 1 (`standalone_question` in the run CSV), so
each variant differs only in the query text. Production retriever (resolver + BM25 + gemini-embedding-2, RRF),
top 8 as in production. Dev split only; first-turn questions only, since a follow-up such as "and deployers?" is
meaningless without the rewrite. Cases: answered in run 1 and with a gold provision.

  uv run --env-file .env python -m evals.rewrite_retrieval_ab     # writes evals/results/rewrite_retrieval_ab.json
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from app.retrieval.search import Retriever

from .run_retrieval_eval import matches

R = Path(__file__).parent / "results"
RUN = R / "e2e_all_gemini-3.8-flash_legal.csv"
K = 8


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def main() -> None:
    with RUN.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if r["split"] == "dev" and not r["turn1"] and r["path"] == "answer" and r["gold_ids"]]
    retr = Retriever(embedder="gemini2")
    variants = {
        "original": lambda r: r["question"],
        "rewrite": lambda r: r["standalone_question"],
        "both": lambda r: f"{r['question']}\n{r['standalone_question']}",
    }
    ranks: dict[str, dict[str, int | None]] = {v: {} for v in variants}
    for r in rows:
        gold = r["gold_ids"].split()
        for v, q in variants.items():
            hits, _ = retr.retrieve(q(r), k=K)
            ranks[v][r["case_id"]] = next((i + 1 for i, h in enumerate(hits) if matches(h.chunk, gold)), None)

    def metrics(ids):
        out = {}
        for v in variants:
            rk = [ranks[v][c] for c in ids]
            out[v] = {f"recall@{n}": round(sum(1 for x in rk if x and x <= n) / len(rk), 3) for n in (1, 3, 5, 8)}
            out[v]["mrr@8"] = round(sum(1 / x for x in rk if x) / len(rk), 3)
        return out

    all_ids = [r["case_id"] for r in rows]
    changed = [r["case_id"] for r in rows if _norm(r["question"]) != _norm(r["standalone_question"])]
    paired = {}
    for a, b in (("rewrite", "original"), ("both", "rewrite"), ("both", "original")):
        found_a = {c for c in all_ids if ranks[a][c]}
        found_b = {c for c in all_ids if ranks[b][c]}
        better = sum(1 for c in all_ids if (ranks[a][c] or 99) < (ranks[b][c] or 99))
        worse = sum(1 for c in all_ids if (ranks[a][c] or 99) > (ranks[b][c] or 99))
        paired[f"{a} vs {b}"] = {"found_only_by_first@8": len(found_a - found_b),
                                 "found_only_by_second@8": len(found_b - found_a),
                                 "gold_ranked_higher_by_first": better, "gold_ranked_higher_by_second": worse}
    lost = [c for c in all_ids if ranks["original"][c] and not ranks["rewrite"][c]]
    gained = [c for c in all_ids if ranks["rewrite"][c] and not ranks["original"][c]]
    by_id = {r["case_id"]: r for r in rows}
    doc = {"n": len(all_ids), "n_rewritten": len(changed), "k": K, "all": metrics(all_ids),
           "rewritten_only": metrics(changed) if changed else {}, "paired": paired,
           "examples_lost_by_rewrite": [{"case": c, "original": by_id[c]["question"],
                                         "rewrite": by_id[c]["standalone_question"], "gold": by_id[c]["gold_ids"]}
                                        for c in lost[:5]],
           "examples_gained_by_rewrite": [{"case": c, "original": by_id[c]["question"],
                                           "rewrite": by_id[c]["standalone_question"], "gold": by_id[c]["gold_ids"]}
                                          for c in gained[:5]]}
    (R / "rewrite_retrieval_ab.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps(doc, indent=1))


if __name__ == "__main__":
    main()
