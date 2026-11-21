"""Answer-style comparison for the Evaluation page: Legal detail vs Explanatory (internal key "plain"), same model
(gemini-3.8-flash, thinking low), same 1,000 cases, both graded by the same style-aware judge prompt (Legal: the
`judgev2` re-grade). Compared on the cases answered in both styles.

  uv run python -m evals.summarize_styles        # writes evals/results/style_comparison.json
"""

from __future__ import annotations

import csv
import json
import re
import statistics as st
from pathlib import Path

R = Path(__file__).parent / "results"
STYLES = [  # (key, label, run CSV, judge review CSV)
    ("legal", "Legal detail", "e2e_all_gemini-3.8-flash_legal.csv", "e2e_all_gemini-3.8-flash_legal_judgev2_review.csv"),
    ("plain", "Explanatory", "e2e_all_gemini-3.8-flash_plain.csv", "e2e_all_gemini-3.8-flash_plain_review.csv"),
]
SELECTED = "legal"
ASPECTS = ["correctness", "completeness", "grounding", "citations", "clarity"]
JARGON = ["placing on the market", "putting into service", "notwithstanding", "pursuant to", "referred to in",
          "in accordance with", "without prejudice", "thereof", "therein", "hereinafter",
          "union harmonisation legislation", "conformity assessment"]


def _read(name: str) -> dict:
    with (R / name).open(encoding="utf-8") as f:
        return {r["case_id"]: r for r in csv.DictReader(f)}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _plain_text(t: str) -> str:  # without citations and markdown, for text measures
    return re.sub(r"[*_#>`]", "", re.sub(r"\[[^\]]+\]", "", t))


def _words(t: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'-]*", _plain_text(t))


def _sentences(t: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+|\n+", _plain_text(t)) if _words(x)]


def _syllables(w: str) -> int:
    w = w.lower()
    groups = re.findall(r"[aeiouy]+", w)
    return max(1, len(groups) - (1 if w.endswith("e") and len(groups) > 1 else 0))


def flesch(t: str) -> float:
    """Flesch reading ease (higher = easier; under 30 reads as 'very difficult')."""
    w = _words(t)
    s = max(1, len(_sentences(t)))
    return 206.835 - 1.015 * len(w) / s - 84.6 * sum(_syllables(x) for x in w) / max(1, len(w))


def main() -> None:
    raw = {k: _read(run) for k, _, run, _ in STYLES}
    rev = {k: _read(review) for k, *_, review in STYLES}
    first = STYLES[0][0]
    both = [c for c in raw[first] if all(raw[k][c]["path"] == "answer" for k in raw)]

    out = []
    for k, label, *_ in STYLES:
        d, j = raw[k], rev[k]

        def jmean(a, j=j):  # paired: only cases where both styles have a score for this aspect
            v = [_num(j[c][f"judge_{a}"]) for c in both
                 if all(_num(rev[s][c][f"judge_{a}"]) is not None for s in rev)]
            return round(st.mean(v), 2)

        out.append({
            "key": k, "label": label,
            "judge_overall": jmean("overall"), **{a: jmean(a) for a in ASPECTS},
            "facts_found": sum(d[c]["facts_ok"] == "True" for c in both),
            "words_p50": round(st.median(len(_words(d[c]["answer"])) for c in both)),
            "words_per_sentence_p50": round(st.median(len(_words(d[c]["answer"])) / max(1, len(_sentences(d[c]["answer"])))
                                                      for c in both), 1),
            "flesch_p50": round(st.median(flesch(d[c]["answer"]) for c in both)),
            "jargon_per_answer": round(st.mean(sum(d[c]["answer"].lower().count(p) for p in JARGON) for c in both), 2),
            "citations_p50": round(st.median(len(re.findall(r"\[[^\]]+\]", d[c]["answer"])) for c in both)),
            "ttft_p50_s": round(st.median(float(d[c]["time_to_first_token_s"]) for c in both), 1),
            "answer_cost_usd": round(sum(_num(r["cost_usd"]) or 0 for r in d.values()), 2),
        })
    ov = [(_num(rev["legal"][c]["judge_overall"]), _num(rev["plain"][c]["judge_overall"])) for c in both]
    doc = {"n_shared": len(both), "n_cases": len(raw[first]), "model": "gemini-3.8-flash", "judge": "claude-sonnet-5-5",
           "selected": SELECTED, "styles": out,
           "plain_better": sum(b > a for a, b in ov), "plain_worse": sum(b < a for a, b in ov),
           "facts_lost": sum(raw["legal"][c]["facts_ok"] == "True" and raw["plain"][c]["facts_ok"] != "True" for c in both),
           "facts_gained": sum(raw["legal"][c]["facts_ok"] != "True" and raw["plain"][c]["facts_ok"] == "True" for c in both)}
    (R / "style_comparison.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps(doc, indent=1))


if __name__ == "__main__":
    main()
