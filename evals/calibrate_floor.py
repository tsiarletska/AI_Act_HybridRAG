"""Calibrate the dense-similarity relevance floor (no LLM).

Queries whose best dense similarity is below the floor are refused before any LLM call
(saves tokens). Off-topic queries near the domain (GDPR, US AI policy) score high and
are left to the LLM scope classifier.

Rule (same for every embedder): floor = (lowest in-scope dev similarity - 0.03), rounded down
to 0.01, so no dev question is blocked. The local floor 0.60 predates this rule and satisfies it.

usage: uv run --env-file .env python -m evals.calibrate_floor --embedder local|gemini1|gemini2
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import yaml

from app.retrieval.search import Retriever

OFF_TOPIC = [
    "Write a Python function to reverse a linked list", "What's the weather in Paris tomorrow?",
    "Give me a recipe for lasagna", "Who won the football world cup in 2022?",
    "Translate 'good morning' into German", "Write a poem about the sea", "What is the capital of Australia?",
    "How do I fix a CSS flexbox alignment issue?", "Explain quantum entanglement",
    "What are the GDPR rules on data subject access requests?", "How do I train a neural network in PyTorch?",
    "Recommend a good laptop for gaming", "What is the best stock to buy now?", "Tell me a joke",
    "How does the US regulate AI?",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", default="local")
    name = ap.parse_args().embedder
    r = Retriever(embedder=name)
    in_scope = [c["q"] for c in yaml.safe_load(Path("evals/retrieval_cases.yaml").read_text())]

    def top(qs):
        out = []
        for q in qs:
            r.search(q, k=1)
            out.append(r.last_top_dense)
        return np.array(out)

    o, i = top(OFF_TOPIC), top(in_scope)
    # held-out check: only the count is recorded, never which questions (the test set is frozen)
    held = top([c["q"] for c in yaml.safe_load(Path("evals/retrieval_cases_test.yaml").read_text())])
    rule = math.floor((float(i.min()) - 0.03) * 100) / 100
    chosen = 0.60 if name == "local" else rule
    grid = sorted({round(x, 2) for x in np.arange(rule - 0.10, rule + 0.11, 0.05)} | {chosen})
    rows = [
        {"floor": t, "off_topic_blocked": round(float(np.mean(o < t)), 3), "in_scope_blocked": round(float(np.mean(i < t)), 3)}
        for t in grid
    ]
    res = {
        "embedder": name,
        "off_topic": dict(zip(OFF_TOPIC, np.round(o, 3).tolist())),
        "in_scope_min": round(float(i.min()), 3),
        "in_scope_median": round(float(np.median(i)), 3),
        "off_topic_max": round(float(o.max()), 3),
        "sweep": rows,
        "rule_floor": rule,
        "chosen": chosen,
        "chosen_blocks_off_topic": round(float(np.mean(o < chosen)), 3),
        "chosen_blocks_in_scope": round(float(np.mean(i < chosen)), 3),
        "held_out_test_blocked": f"{int((held < chosen).sum())}/{len(held)}",
    }
    Path(f"evals/results/relevance_floor_{name}.json").write_text(json.dumps(res, indent=2))
    for row in rows:
        print(row)
    print({k: res[k] for k in ("in_scope_min", "in_scope_median", "off_topic_max", "chosen",
                               "chosen_blocks_off_topic", "chosen_blocks_in_scope", "held_out_test_blocked")})

if __name__ == "__main__":
    main()
