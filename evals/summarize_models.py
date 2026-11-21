"""Answer-model comparison for the Evaluation page: judge scores, facts, latency and cost of the end-to-end runs,
on the cases every run answered (the guard is not deterministic, so a few cases take a different path per run).

  uv run python -m evals.summarize_models        # writes evals/results/model_selection.json
"""

from __future__ import annotations

import csv
import json
import statistics as st
from pathlib import Path

R = Path(__file__).parent / "results"
RUNS = [  # (key, label, thinking, run file stem)
    ("gemini_low", "gemini-3.8-flash", "thinking low (0 thinking tokens)", "e2e_all_gemini-3.8-flash_legal"),
    ("gemini_medium", "gemini-3.8-flash", "thinking medium", "e2e_all_gemini-3.8-flash_legal_think-medium"),
    ("mistral_large4", "mistral-large-4", "reasoning low (lowest available)", "e2e_all_mistral-large-4_legal"),
]
SELECTED = "gemini_low"
ASPECTS = ["correctness", "completeness", "grounding", "citations", "clarity"]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return {r["case_id"]: r for r in csv.DictReader(f)}


def main() -> None:
    raw = {k: _read(R / f"{stem}.csv") for k, *_, stem in RUNS}
    rev = {k: _read(R / f"{stem}_review.csv") for k, *_, stem in RUNS}
    first = RUNS[0][0]
    shared = [c for c in raw[first]
              if all(raw[k][c]["path"] == "answer" and raw[k][c]["ms_answer_first_token"] for k in raw)]

    def mean(k, col):
        v = [x for x in (_num(rev[k][c][col]) for c in shared) if x is not None]
        return round(st.mean(v), 2)

    out = []
    for k, label, thinking, stem in RUNS:
        ft = sorted(float(raw[k][c]["ms_answer_first_token"]) / 1000 for c in shared)
        out.append({
            "key": k, "model": label, "thinking": thinking, "run": stem,
            "judge_overall": mean(k, "judge_overall"),
            **{a: mean(k, f"judge_{a}") for a in ASPECTS},
            "facts_found": sum(raw[k][c]["facts_ok"] == "True" for c in shared),
            "first_word_p50_s": round(st.median(ft), 1),
            "first_word_p90_s": round(ft[int(0.9 * len(ft))], 1),
            "first_word_max_s": round(ft[-1], 1),
            "answer_cost_usd": round(sum(_num(r["cost_usd"]) or 0 for r in raw[k].values()), 2),
        })
    # production figures for the selected run, over all cases it answered (what a user sees end to end)
    ans = [r for r in raw[SELECTED].values() if r["path"] == "answer" and r["time_to_first_token_s"]]
    tps = []
    for r in ans:
        out_tok = int(r["answer_tokens_in_out"].split("/")[1])
        dt = (float(r["ms_answer"]) - float(r["ms_answer_first_token"])) / 1000
        if dt > 0.2 and out_tok > 20:  # skip one-chunk answers, where speed is undefined
            tps.append(out_tok / dt)
    production = {"run": dict((k, s) for k, *_, s in RUNS)[SELECTED], "n_answers": len(ans),
                  "ttft_p50_s": round(st.median(float(r["time_to_first_token_s"]) for r in ans), 1),
                  "total_p50_s": round(st.median(float(r["total_s"]) for r in ans), 1),
                  "tokens_per_s_p50": round(st.median(tps))}
    doc = {"production": production, "n_shared": len(shared), "n_cases": len(raw[first]), "style": "legal", "judge": "claude-sonnet-5-5",
           "selected": SELECTED, "runs": out}
    (R / "model_selection.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps(doc, indent=1))


if __name__ == "__main__":
    main()
