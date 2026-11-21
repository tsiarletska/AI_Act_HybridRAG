"""Unblind the human review and compare it with the LLM judge.

  uv run python -m evals.analyze_blind_review     # reads evals/review/blind_review_100_scores.csv + blind_key_100.csv
"""

from __future__ import annotations

import csv
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

D = Path(__file__).parent / "review"


def _read(name):
    with (D / name).open(encoding="utf-8-sig") as f:
        return {r["case_id"]: r for r in csv.DictReader(f)}


def _pearson(x, y):
    mx, my = st.mean(x), st.mean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / ((sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5)


def _rank(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def main():
    sc, key = _read("blind_review_100_scores.csv"), _read("blind_key_100.csv")
    sheet = _read("blind_review_100.csv")
    per = defaultdict(list)        # model -> [(case, human, sonnet)]
    for c, s in sc.items():
        for L in "ABC":
            if s[f"score_{L}"] == "":
                continue
            per[key[c][f"model_{L}"]].append((c, float(s[f"score_{L}"]), float(key[c][f"sonnet_overall_{L}"])))
    out = {"n_cases_scored": len({c for v in per.values() for c, *_ in v}), "models": {}}
    for m, v in per.items():
        out["models"][m] = {"n": len(v), "human_mean": round(st.mean(h for _, h, _ in v), 2),
                            "sonnet_mean": round(st.mean(j for *_, j in v), 2)}
    # pairwise: which model the human preferred, case by case
    by_case = defaultdict(dict)
    for m, v in per.items():
        for c, h, j in v:
            by_case[c][m] = (h, j)
    ms = sorted(per)
    pairs = {}
    for i in range(len(ms)):
        for k in range(i + 1, len(ms)):
            a, b = ms[i], ms[k]
            d = [by_case[c][a][0] - by_case[c][b][0] for c in by_case if a in by_case[c] and b in by_case[c]]
            pairs[f"{a} vs {b}"] = {"first_better": sum(x > 0 for x in d), "second_better": sum(x < 0 for x in d),
                                    "tie": sum(x == 0 for x in d)}
    out["pairwise_human"] = pairs
    # agreement with the judge, all scored answers
    allv = [(h, j) for v in per.values() for _, h, j in v]
    H, J = [h for h, _ in allv], [j for _, j in allv]
    out["agreement"] = {"n_answers": len(allv), "human_mean": round(st.mean(H), 2), "sonnet_mean": round(st.mean(J), 2),
                        "exact": sum(h == j for h, j in allv), "within_1": sum(abs(h - j) <= 1 for h, j in allv),
                        "judge_higher": sum(j > h for h, j in allv), "human_higher": sum(h > j for h, j in allv),
                        "pearson": round(_pearson(H, J), 2), "spearman": round(_pearson(_rank(H), _rank(J)), 2),
                        "human_distribution": {str(k): H.count(k) for k in sorted(set(H))},
                        "sonnet_distribution": {str(k): J.count(k) for k in sorted(set(J))}}
    # biggest disagreements
    big = sorted(((abs(h - j), c, m, h, j) for m, v in per.items() for c, h, j in v), reverse=True)[:8]
    out["largest_gaps"] = [{"case": c, "topic": sheet[c]["topic"], "model": m, "human": h, "sonnet": j} for _, c, m, h, j in big]
    # by topic, human mean per model
    tp = defaultdict(lambda: defaultdict(list))
    for m, v in per.items():
        for c, h, _ in v:
            tp[sheet[c]["topic"]][m].append(h)
    out["by_topic_human"] = {t: {m: round(st.mean(x), 2) for m, x in d.items()} | {"n": len(next(iter(d.values())))}
                             for t, d in sorted(tp.items())}
    (D / "blind_review_100_results.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
