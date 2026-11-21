"""Blind human review sheet: 100 dev cases that all three runs answered, with the three answers in random order
(A/B/C, shuffled per case) and no model names. The mapping is written to a separate key file.

Dev split only, so the frozen test split stays unread. Stratified by topic (proportional, at least 2 per topic),
fixed seed.

  uv run python -m evals.make_blind_review          # writes evals/review/blind_review_100.csv + blind_key_100.csv
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path

R = Path(__file__).parent / "results"
OUT = Path(__file__).parent / "review"
RUNS = {"gemini-3.8-flash (thinking low)": "e2e_all_gemini-3.8-flash_legal",
        "gemini-3.8-flash (thinking medium)": "e2e_all_gemini-3.8-flash_legal_think-medium",
        "mistral-large-4 (reasoning low)": "e2e_all_mistral-large-4_legal"}
N, SEED, MIN_PER_TOPIC = 100, 11, 2


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return {r["case_id"]: r for r in csv.DictReader(f)}


def main() -> None:
    raw = {m: _read(R / f"{s}.csv") for m, s in RUNS.items()}
    rev = {m: _read(R / f"{s}_review.csv") for m, s in RUNS.items()}
    first = next(iter(raw.values()))
    pool = [c for c, r in first.items() if r["split"] == "dev" and all(raw[m][c]["path"] == "answer" for m in raw)]

    by = defaultdict(list)
    for c in pool:
        by[first[c]["category"]].append(c)
    # proportional, at least MIN_PER_TOPIC, never more than the topic has
    quota = {t: min(len(cs), max(MIN_PER_TOPIC, round(N * len(cs) / len(pool)))) for t, cs in by.items()}
    while sum(quota.values()) > N:  # trim the largest topic until the total is exact
        quota[max(quota, key=quota.get)] -= 1
    while sum(quota.values()) < N:
        quota[max(quota, key=lambda t: len(by[t]) - quota[t])] += 1
    rng = random.Random(SEED)
    picked = sorted(c for t, cs in sorted(by.items()) for c in rng.sample(sorted(cs), min(quota[t], len(cs))))

    OUT.mkdir(exist_ok=True)
    sheet, key = [], []
    for i, c in enumerate(picked, 1):
        r = first[c]
        order = list(RUNS)
        rng.shuffle(order)
        sheet.append({
            "no": i, "case_id": c, "topic": r["category"],
            "earlier_turn": r["turn1"], "question": r["question"],
            "expected_behaviour": r["expect"], "gold_provisions": r["gold_labels"],
            **{f"answer_{L}": raw[m][c]["answer"] for L, m in zip("ABC", order)},
            **{f"score_{L}": "" for L in "ABC"},
            "notes": "",
        })
        key.append({"no": i, "case_id": c, **{f"model_{L}": m for L, m in zip("ABC", order)},
                    **{f"sonnet_overall_{L}": rev[m][c]["judge_overall"] for L, m in zip("ABC", order)}})

    # utf-8-sig so Excel / LibreOffice open the long answers with the right encoding
    for name, rows in (("blind_review_100.csv", sheet), ("blind_key_100.csv", key)):
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print({t: sum(first[c]["category"] == t for c in picked) for t in sorted(by)}, "pool", len(pool), "picked", len(picked))


if __name__ == "__main__":
    main()
