# Chunking strategy assessment

**Question:** which way of cutting the AI Act into retrievable pieces gives the best answers, considering the nature of the document?

**Answer:** structure-aware chunking that follows the Act's own hierarchy, with a context header. It is the current production chunker (`app/ingest/chunker.py`).
- At tight context budgets (500–1,500 words) it finds the right provision far more often than the alternatives. It reaches full recall with **half the context** they need; at 3,000 words most strategies converge.
- It is the only strategy that gives paragraph-level citations **and** enables the reference resolver.
- Both of its ingredients help: fine, structure-following boundaries, and the context header.

Reproduce:
```
uv run --env-file .env python -m evals.chunking_eval
uv run --env-file .env python -m evals.chunking_eval --cases evals/retrieval_cases_test.yaml
```
Results: `evals/results/chunking_dev.json`, `evals/results/chunking_test.json`.

## 1. What the document is like, and what that implies

| Property of the AI Act | Implication for chunking |
|---|---|
| Explicit legal hierarchy (chapter › section › article › paragraph › point) with stable HTML anchors (`art_5`, `005.001`) | Boundaries are free and exact. There is no need to guess them with sizes, sentences or embeddings |
| Users and answers must cite provisions ("Art. 5(1)(f)") | A chunk should map to one citable unit; a window spanning two articles cannot be cited |
| Unit sizes vary by ~250×: a definition can be 10 words, Art. 3 has 2,600 words, Art. 5 has 1,800 | No fixed size fits. Small units are kept whole and large ones split at their own points |
| Points depend on their lead-in ("The following AI practices shall be prohibited: … (f) …") | When a paragraph is split into points, the lead-in is repeated in every point chunk |
| Provisions rarely name their subject; context comes from headings ("Section 2 Requirements for high-risk AI systems" › "Article 10 Data and data governance") | The chapter › section › article-title header is attached to each chunk |
| 68 definitions in a single article (Art. 3) | One chunk per definition, carrying its term (also used by the resolver) |
| Recitals explain but do not bind | Recitals are kept separate, one chunk each, and ranked slightly below articles |
| Annexes are lists (use cases, documentation items), often grouped in sections | Section-aware annex splitting, with tiny items packed together |
| Dense cross-references ("referred to in Article 6(2)") | Structural IDs allow a deterministic resolver and one-hop expansion. Neither is possible with anonymous windows |
| Near-verbatim mirrored provisions (e.g. Art. 22 ≈ Art. 54) | A measurement caveat; see §4 |

## 2. Strategies compared

All strategies were built from the same parsed OJ HTML, retrieved with the same embedder (`gemini-embedding-2`) and scored the same way.

| Strategy | How it chunks | Chunks | Median words |
|---|---|---|---|
| `fixed_250` | Sliding windows of 250 words, 40 overlap, structure-blind | 417 | 250 |
| `fixed_500` | Sliding windows of 500 words, 75 overlap | 206 | 500 |
| `recursive_350` | Split at line, then sentence boundaries, packed to ≤ 350 words (LangChain-style), no labels | 287 | 320 |
| `article` | One chunk per article, recital or annex | 306 | 190 (max 2,619) |
| `paragraph` | One chunk per article paragraph; points never split, so Art. 3 is one chunk | 745 | 77 (max 2,619) |
| **`structural`** | Production: paragraph, split into points above 350 words; one chunk per definition; annex points/sections; plus header | 893 | 69 (max 729) |
| `structural_nohdr` | Same chunks, header and label removed (ablation) | 893 | 69 |

**Considered but not run:**
- **Semantic (embedding-breakpoint) chunking:** the Act already has exact semantic boundaries, so learned breakpoints can only approximate them.
- **LLM-generated chunk context ("contextual retrieval"):** the structural header gives the same benefit deterministically, at no cost. The ablation below measures how much it is worth.
- **Whole Act in the context window (~125k tokens):** ~125k input tokens per question, imprecise citations, and less focused answers. Rejected in PLAN §2.2.
- **Small-to-big (retrieve a point, send its paragraph):** an answer-time step, already in PLAN §2.2 (lead-in and one-hop expansion).

## 3. How it was measured

- **Strategy-agnostic gold.** The gold labels are structural IDs, which other strategies do not have.
  - A gold unit is the own text of the matching production chunk, with the repeated lead-in removed.
  - It counts as **found** when ≥ 50% of its word 5-grams are in the retrieved text. Neighbouring windows are pooled, so a unit split across two windows still counts.
- **Recall at a fixed context budget** (500 / 1,500 / 3,000 words) is the deciding metric.
  - Ranked chunks are taken until the budget is full; the last one is truncated, and header and label words count.
  - Recall@k would reward big chunks: 5 articles hold ~2,000 words, 5 points ~650.
  - 3,000 words is roughly what the answer prompt holds.
- **Precision** is the share of retrieved 5-grams that belong to the gold unit.
- **Citability** is the share of chunks whose text lies within one citable unit (≥ 90% of 5-grams), at paragraph/point level or at article level.
- **Retrieval:**
  - **dense only** (the clean comparison);
  - the production **hybrid** (BM25 weight 0.25 + dense, RRF);
  - both **without** the reference resolver, which only works on structural chunks.
- **Discipline:** the decision was made on dev (50 questions); test (25, frozen) was run once. Per-case diagnosis was done on dev only.

## 4. Results

Recall at a fixed context budget (words). D = dense only, H = hybrid.

**Dev (50 questions; the decision was made here)**

| Strategy | D@500 | D@1500 | D@3000 | H@500 | H@1500 | H@3000 |
|---|---|---|---|---|---|---|
| fixed_250 | 0.64 | 0.84 | 0.88 | 0.60 | 0.84 | 0.88 |
| fixed_500 | 0.42 | 0.80 | 0.86 | 0.44 | 0.80 | 0.88 |
| recursive_350 | 0.58 | 0.86 | 0.90 | 0.66 | 0.84 | 0.90 |
| article | 0.72 | 0.90 | 1.00 | 0.82 | 0.94 | 1.00 |
| paragraph | 0.90 | 0.96 | 0.98 | 0.86 | 0.98 | 1.00 |
| **structural** | **0.94** | **1.00** | **1.00** | **0.96** | **1.00** | **1.00** |
| structural_nohdr | 0.76 | 0.92 | 0.94 | 0.84 | 0.88 | 0.94 |

**Test (25 questions, frozen, run once)**

| Strategy | D@500 | D@1500 | D@3000 | H@500 | H@1500 | H@3000 |
|---|---|---|---|---|---|---|
| fixed_250 | 0.68 | 0.92 | 0.92 | 0.68 | 0.92 | 0.96 |
| fixed_500 | 0.52 | 0.72 | 0.88 | 0.52 | 0.84 | 0.92 |
| recursive_350 | 0.60 | 0.84 | 0.92 | 0.64 | 0.92 | 0.92 |
| article | 0.60 | 0.80 | 0.96 | 0.80 | 0.92 | 0.96 |
| paragraph | 0.68 | 0.84 | 0.96 | 0.84 | 0.92 | 0.96 |
| **structural** | **0.96** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** |
| structural_nohdr | 0.92 | 0.92 | 0.92 | 0.92 | 0.96 | 0.96 |

**Other measures (dev):**

| Strategy | Citable at paragraph level¹ | Citable at article level¹ | Precision @500 (D) | Words in top 5 chunks |
|---|---|---|---|---|
| fixed_250 | 0.17 | 0.49 | 0.20 | 1,250 |
| fixed_500 | 0.02 | 0.24 | 0.18 | 2,492 |
| recursive_350 | 0.22 | 0.49 | 0.21 | 1,541 |
| article | 0.67 | 1.00 | 0.32 | 2,068 |
| paragraph | 0.99 | 1.00 | 0.37 | 804 |
| **structural** | 0.96 | 0.97 | **0.38** | **660** |
| structural_nohdr | 0.96 | 0.97 | 0.24 | 682 |

¹ Measured from text: the share of chunks with ≥ 90% of their unique 5-grams inside one unit. For the **labelled** strategies (article, paragraph, structural) this is an artifact. Each of their chunks carries a label, so all are citable by construction: at article level for `article`, and at paragraph/point level for `paragraph` and `structural`. The measure falls below 1.0 because mirrored provisions (Art. 22 ≈ Art. 54, Art. 16 ≈ Art. 17) share wording, and finer point chunks hit that more often than whole paragraphs. The measure is meaningful for the unlabelled window strategies.

**Reading the results:**
1. **Structure-blind chunking is clearly worse at tight budgets.**
   - Fixed windows and the recursive splitter trail by 28–52 points at 500 words (both sets).
   - Only 2–22% of their chunks can be cited at paragraph level.
   - Bigger windows are worse (fixed_500 < fixed_250): the relevant sentence is diluted.
2. **The advantage is at small budgets, where it matters for cost.**
   - At 3,000 words most strategies converge. On test, article, paragraph and fixed_250 (hybrid) all reach 0.96, against structural's 1.00, which our < 5 pp rule counts as a tie.
   - Structural is the only strategy at 1.00 already at 1,500 words, on both sets and in both modes. The same recall needs about half the context, so prompts are cheaper, answers faster and the model less distracted.
   - **Hypothesis for the end-to-end eval (M5):** the answer context could shrink from ~3,000 to ~1,500 words. Finding one gold unit is not the same as covering every provision a question needs, so this is measured before anything changes.
3. **Too coarse also loses.** Article-level chunks are citable only at article level, and fill the budget with whole articles (Art. 5 is 1,800 words). They trail structural by 14–36 points at 500 words.
4. **Paragraph-level is the closest competitor and loses exactly where the Act is uneven.**
   - On dev it trails by only 2–4 points dense (a tie), but by 10 points hybrid at 500 words. On test it trails by 28 points at D@500 and 16 points at D@1500 and H@500.
   - On dev, every question it misses that structural finds is in an **oversized unit**: Art. 5(1) (prohibitions) and Art. 3 (one 2,600-word chunk holding all 68 definitions).
   - On dev, there is no case where paragraph-level finds the passage and structural does not. Test cases were not inspected.
   - Splitting large paragraphs into points and definitions fixes exactly this, and these are among the most-asked parts of the Act.
   - **Tie-break on dev dense:** citability nominally favours paragraph (0.99 vs 0.96), but that is the artifact in footnote ¹. What breaks the tie is the hybrid result (+10 dev) and the test result (+16 to +28).
5. **Both ingredients help, and their relative size is not stable on sets this small.**
   - **Boundaries:** following the Act's structure, even without a header, beats fixed_250 at D@500 by +12 on dev and +24 on test.
   - **Header:** chapter › section › article title adds +4 to +18 points in all 8 dev/test cells at 500 and 1,500 words: +18 at dev D@500, but +4 at test D@500.
   - **Finer granularity** (structural vs paragraph) adds +2 to +28, larger on test.
   - Both are deterministic and free. The header is the deterministic version of "contextual retrieval".
6. **The structural resolver is an extra benefit on top.** With it, retrieval reaches recall@5 = 1.00 on test (`retrieval_test_gemini2.json`). Window strategies cannot use it.

**Caveats:**
- **Home advantage.** The dev questions, the BM25 glossary and the BM25 weight were developed on the structural chunks. That is why dense-only is the primary view. The ranking is the same in both modes and on the test set.
- **Small sets.** With 50 and 25 questions, 1 question equals 2 or 4 points. Gaps under 5 points are treated as ties. The conclusion rests on gaps that are consistent across sets and modes, and on the per-case diagnosis.
- **Cost.** Indexing is a one-off: structural embeds ~104k words including headers, against ~87–104k for the others. Per question it puts the fewest words in context.

## 5. Decision

**Keep the structural chunker.**
- At 500 and 1,500 words it is never beaten on either set.
  - It wins by ≥ 5 points against every structure-blind and article-level variant.
  - Against paragraph-level it ties on dev (D@500, D@1500, H@1500) and wins by 10–28 points in the other five cells.
- At 3,000 words all strong strategies tie.
- It is the only strategy that combines:
  - full recall at half the context;
  - paragraph-level citations;
  - the reference resolver.

Both the header and the point/definition splits (Art. 3, Art. 5) stay mandatory. The context-budget reduction (~3,000 → ~1,500 words) is a hypothesis for the M5 end-to-end eval.
