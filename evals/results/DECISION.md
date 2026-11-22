# Decisions from the end-to-end evaluation (2026-11-20 to 2026-11-21)

Source data: `model_selection.json`, `style_comparison.json`, `rewrite_retrieval_ab.json` (this folder) and
`evals/review/blind_review_100_results.json`. Method and caveats: `docs/METHODOLOGY.md` §6, §8.4, §8.5.

## Generation model: `gemini-3.8-flash`, thinking low

1,000 cases per run, Legal detail style, same retrieval, guard and prompts. Judge: Claude Sonnet 5.5, on the 676 cases
all three runs answered.

| | Gemini, thinking low (selected) | Gemini, thinking medium | Mistral Large 4, reasoning low |
|---|---|---|---|
| Judge overall (0-10) | 9.12 | 9.09 | 9.13 |
| Expected facts found (of 676) | 614 | 611 | 601 |
| Answer model, first token, median / p90 | 1.8 s / 2.2 s | 6.3 s / 10.0 s | 6.8 s / 26.2 s |
| Answer cost, 1,000 cases | $1.79 | $3.46 | $1.98 |
| Blind human review, 99 cases (0-10) | 8.82 | 8.99 | 9.05 |

The first-token times are the answer model alone. What the user waits for the first word of the selected setup, including the floor, guard and retrieval, is 3.3 s median and 4.1 s p95 (`latency_by_path` in the run 1 JSON).

**Decision:** Gemini without reasoning. Quality is tied on the judge (differences under the judge's own run-to-run
variation of about 0.1), and the human reviewer leaned towards Mistral (45 vs 27 case wins, not significant after
correcting for three comparisons). Gemini without reasoning starts answering 3-4 times sooner, has no long waits, and
costs about half as much as Gemini with reasoning. Mistral Large 4 cannot switch reasoning off.

## Answer style: Legal detail stays the default

Same model, same 1,000 cases, same style-aware judge prompt; 683 cases answered in both styles. Judge overall: Legal
detail 9.00, Explanatory 8.54 (better on 82 cases, worse on 315); expected facts 615 vs 599. The explanatory prompt
removed legal jargon (1.15 → 0.16 phrases per answer) but stayed dense (Flesch 19 vs 25) and paraphrasing cost some
accuracy. Explanatory remains available as a toggle; its prompt needs another iteration.

## Query rewriting: kept

Retrieval with the user's raw message vs the guard's rewrite, 395 dev questions: top-8 hit rate 94.7% vs 95.4%
(gold ranked higher 40 vs 41 times, a tie). Kept because it turns follow-ups and unclear wording into complete questions
in the Act's terms (user's decision).
