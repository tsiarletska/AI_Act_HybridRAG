# Evaluation log

Every evaluation run on this project, in order. For each: why it was run, method, data, results, decision and caveats. Raw results are the JSON files in `evals/results/`; every number below can be reproduced with the command given.

**Question sets** (no LLM involved in any evaluation so far):
- `evals/retrieval_cases.yaml`: **dev**, 50 questions (43 natural-language, 7 that name an article). Used for all tuning.
- `evals/retrieval_cases_test.yaml`: **test**, 25 questions, written before any tuning and **frozen**. Run once per final configuration, with failures not printed.
- Gold labels are chunk IDs (e.g. `art_5_1_f`), found by phrase search over the parsed text, never from the model's memory of the Act.

**Rule for every comparison:** decide on dev, confirm on test once. A gap under 5 percentage points is a tie (1 question = 2 pp on dev, 4 pp on test).

---

## E1 — Retrieval ablation, local embeddings · 2026-11-18

- **Why:** build the retrieval pipeline step by step, and keep only components that measurably help.
- **Method:** recall@k (a gold chunk among the top k) and MRR. Each component added in turn: BM25 → dense (local `bge-small`) → hybrid (RRF) → lay→legal glossary → article-title ranker → reference resolver.
- **Run:** `uv run python -m evals.run_retrieval_eval --embedder local [--cases evals/retrieval_cases_test.yaml]`
- **Results** (recall@5 / MRR):

| Config | Dev (50) | Test (25), before tuning | Test, final |
|---|---|---|---|
| BM25 | 0.66 / 0.49 | 0.84 / 0.64 | 0.84 / 0.64 |
| Dense (bge-small) | 0.66 / 0.54 | 0.80 / 0.65 | 0.80 / 0.65 |
| Hybrid (RRF) | 0.78 / 0.67 | 0.80 / 0.73 | 0.80 / 0.73 |
| + glossary | 0.82 / 0.70 | – | 0.80 / 0.73 |
| + title ranker | 0.78 / 0.67 | – | – |
| **+ resolver (product)** | **0.94 / 0.82** | 0.84 / 0.75 | **0.88 / 0.81** |

- **Decision:**
  - Keep hybrid + glossary + resolver.
  - **Reject** the title ranker: it lowered dev recall, and a weight sweep found its best weight is 0.
- **Caveat:** the test set was viewed three times during this stage. One resolver change (recognising "counts as") was made after test misses were visible. The set was frozen afterwards.
- **Files:** `retrieval_dev_local.json`, `retrieval_test_local.json`, `retrieval_test_baseline.json`.

## E2 — Relevance floor calibration · 2026-11-18

- **Why:** refuse clearly off-topic questions **before any LLM call**, to save tokens.
- **Method:**
  - Take the best dense similarity of 15 off-topic questions (code, weather, recipes, GDPR, US AI policy, …) and of the 50 dev questions.
  - Rule: floor = lowest in-scope dev similarity − 0.03.
  - Afterwards, count the test questions blocked (as a count only).
- **Run:** `uv run --env-file .env python -m evals.calibrate_floor --embedder local|gemini2`
- **Results:**

| Embedder | Floor | Off-topic blocked | Dev blocked | Test blocked |
|---|---|---|---|---|
| local | 0.60 | 13/15 | 0/50 | – |
| gemini2 | 0.64 | 13/15 | 0/50 | 0/25 (lowest 0.729) |

- **Decision:** floors are set per embedder. The two that pass (GDPR, US AI policy) are near the topic, so the LLM scope classifier must handle them.
- **Caveat:** the floor must be applied to the **rewritten** standalone question. A raw follow-up like "and deployers?" would score low.
- **Files:** `relevance_floor_<embedder>.json`.

## E3 — Embedder comparison · 2026-11-18

- **Why:** the user proposed Gemini embeddings instead of the local model.
- **Method:**
  - Same questions and same pipeline (product config) with three embedders:
    - local `bge-small-en-v1.5`;
    - `gemini-embedding-001` (task_type, 768-d);
    - `gemini-embedding-2` (text prefixes, 768-d).
  - Two API pitfalls were found by smoke tests first: gemini-embedding-2 merges several texts sent in one request into one vector, and ignores `task_type`.
- **Run:** `uv run --env-file .env python -m evals.run_retrieval_eval --embedder gemini1|gemini2 [--cases …test.yaml]`
- **Results** (recall@1 / recall@5 / MRR):

| Embedder | Dev (50) | Test (25, run once) |
|---|---|---|
| local bge-small | 0.74 / 0.94 / 0.82 | 0.76 / 0.88 / 0.81 |
| gemini-embedding-001 | 0.84 / 0.98 / 0.91 | 0.92 / 1.00 / 0.96 |
| **gemini-embedding-2** | **0.92 / 0.98 / 0.95** | **0.96 / 1.00 / 0.98** |

- **Decision:** `gemini-embedding-2` is the default, and it wins on dev alone.
- **Side effect:** query embedding needs `GEMINI_API_KEY` whichever answer model wins. This is deliberate: both answer candidates get identical retrieval. If the API fails, search falls back to BM25 + resolver.
- **Caveat:** the test set is now saturated (recall@5 = 1.00). It can no longer tell later retrieval changes apart.
- **Files:** `retrieval_{dev,test}_{local,gemini1,gemini2}.json`.

## E4 — BM25 weight in fusion · 2026-11-18

- **Why:** with gemini-embedding-2, dense-only search (dev recall@5 0.98) beat equal-weight hybrid (0.88), so BM25 was pulling results down.
- **Method:** sweep the BM25 weight over 0 / 0.25 / 0.5 / 0.75 / 1.0 (dense = 1), on **dev only**, judged by recall@1 and MRR (recall@5 was saturated).
- **Run:** `uv run --env-file .env python -m evals.sweep_bm25_weight`
- **Results** (gemini2, recall@1 / MRR): w=0 → 0.94 / 0.963 · **w=0.25 → 0.92 / 0.953** · w=0.5 → 0.86 / 0.920 · w=1 → 0.82 / 0.895.
- **Decision:** weight 0.25 for the Gemini embedders, 1.0 for local.
  - It costs one dev question against w=0, which is within noise.
  - It keeps exact-term matching for numbers and defined terms.
  - It keeps the BM25 index warm, since BM25 is the fallback when the embedding API is down.
- **File:** `bm25_weight_sweep.json`.

## E5 — Chunking strategy assessment · 2026-11-18

- **Why:** the user asked which chunking approach fits the nature of the document best. The full write-up is `docs/CHUNKING.md`.
- **Strategies (7), all built from the same parsed OJ HTML:**
  - fixed windows of 250 and 500 words with overlap;
  - recursive splitter (350 words);
  - one chunk per article;
  - one chunk per paragraph;
  - **structural** (production);
  - structural without the header.
- **Method:**
  - **Strategy-agnostic gold.** A gold unit counts as found when ≥ 50% of its own word 5-grams are in the retrieved text. "Own text" means with the repeated lead-in removed.
  - **Recall at a fixed context budget** (500 / 1,500 / 3,000 words) is the deciding metric, because recall@k rewards big chunks.
  - Also measured: precision, citability, cost.
  - Retrieval was run dense-only (the primary view) and hybrid, both **without** the resolver, which only structural chunks can use.
  - Offline checks before any API call: every unit's own text is in the source text (0 misses), and lead-in stripping was verified.
- **Run:** `uv run --env-file .env python -m evals.chunking_eval [--cases evals/retrieval_cases_test.yaml]`
- **Results** (recall, dense @500 / @1500 / @3000 words):

| Strategy | Dev (50) | Test (25, run once) | Citable at paragraph level | Words in top 5 |
|---|---|---|---|---|
| fixed_250 | 0.64 / 0.84 / 0.88 | 0.68 / 0.92 / 0.92 | 0.17 | 1,250 |
| fixed_500 | 0.42 / 0.80 / 0.86 | 0.52 / 0.72 / 0.88 | 0.02 | 2,492 |
| recursive_350 | 0.58 / 0.86 / 0.90 | 0.60 / 0.84 / 0.92 | 0.22 | 1,541 |
| article | 0.72 / 0.90 / 1.00 | 0.60 / 0.80 / 0.96 | article-level only | 2,068 |
| paragraph | 0.90 / 0.96 / 0.98 | 0.68 / 0.84 / 0.96 | by label | 804 |
| **structural** | **0.94 / 1.00 / 1.00** | **0.96 / 1.00 / 1.00** | by label | **660** |
| structural, no header | 0.76 / 0.92 / 0.94 | 0.92 / 0.92 / 0.92 | by label | 682 |

- **Findings:**
  - Structure-blind chunking trails by 28–52 pp at 500 words.
  - Structural reaches full recall at 1,500 words, on both sets and in both modes. At 3,000 words the strong strategies tie.
  - Paragraph-level is the closest competitor: it ties on dev (dense) and trails by 16–28 pp on test. On dev, its misses are all in oversized units (Art. 3 as one 2,600-word chunk, and Art. 5(1)).
  - The header and fine granularity each help in every dev/test cell at 500 and 1,500 words. Their relative size varies (header: +18 pp on dev, +4 pp on test at 500 words).
- **Decision:** keep the structural chunker. Shrinking the answer context from about 3,000 to about 1,500 words is a **hypothesis** for the end-to-end eval: finding one gold unit is not the same as covering every provision a question needs.
- **Caveats:**
  - Home advantage: the dev questions, glossary and BM25 weight were developed on the structural chunks, which is why dense-only is the primary view.
  - Small sets.
  - Measured citability tops out at ~96% because of mirrored provisions (Art. 22 ≈ Art. 54).
- **Review:** an independent review of the first write-up caught three overstatements, which were corrected:
  - "best at every budget" was false at 3,000 words;
  - a dev-only header figure was presented as general;
  - a citability tie-break was a measurement artifact.
- **Files:** `chunking_dev.json`, `chunking_test.json`.

## E6 — Manual browser check of the built chat · 2026-11-18

- **Why:** see the whole pipeline working end to end before the formal end-to-end eval.
- **Method:** questions typed into the running app, checked in the browser and through the API. This is not a benchmark; it found two bugs.
- **Results:**
  - In-scope question (workplace emotion recognition): correct, 7 citations, $0.0027, 6.2 s.
  - Follow-up "and for high-risk systems?": rewritten to a standalone question; dates correct (2 Aug 2026, 2 Aug 2027 for Annex I products, 2030 for public authorities).
  - Guardrail stages: Python-code request refused by the pre-filter (0 API calls); weather refused by the floor (similarity 0.525, 0 LLM calls); GDPR passes the floor (0.645) and is refused by the guard (1 Flash-Lite call, no answer-model call).
- **Bugs found and fixed:**
  1. **"When do the rules for general-purpose AI models apply?"** was answered without Art. 113, which sets every date of application, because retrieval missed it.
     - Fix: a deterministic resolver rule. "When / deadline / apply from …" questions add Art. 113 as a scope hit, which boosts it without overriding other results. Covered by tests.
     - Dev retrieval unchanged (recall@5 0.98, MRR 0.953). The test set was not re-run: it is saturated and frozen.
     - After the fix, the answer is "2 August 2025" with [Art. 113(b)].
  2. **Citation validity.** The model cited `[Annex III, point 1(c)]` from the excerpt `Annex III, point 1`, and it was flagged as invalid.
     - Fix: citations that narrow a retrieved excerpt are valid and link to it, in both server and UI. Covered by tests.
  3. UI: a message sent while an answer was streaming was silently dropped. Fixed.
- **Found in review after the browser check (fixed, with tests):**
  4. **Concurrency.** Search stored the best similarity on the shared retriever, so with two users at once a request could apply the floor using another request's score. Retrieval now returns its own score (`Retriever.retrieve`); a test runs 40 parallel retrievals.
  5. **Pre-filter false refusals.** "Create a compliance checklist for my app", "the risk class of …", "a chatbot on my website", "API provider" and "the function of the AI Office" were refused as code requests. The noun list is now code-specific only; all are negative tests.
  6. **The Art. 113 date rule fired on conditional "when"** (2 of the 3 dev questions with "when", e.g. "When can police use …"). It now needs a date sense ("when does … apply", "deadline", "which date", …). Dev retrieval unchanged.

## E8 — Multilingual retrieval: translate to English, or search as is? · 2026-11-19

- **Why:** the planned multilingual feature (5 languages: English, Lithuanian, Polish, Finnish, French) would keep **one English index** and swap in the official text of the same chunk IDs in the user's language. That rests on a hypothesis: a question translated into English by the guard finds the right provisions as well as an English question does. Run on **dev only**; the test set is saturated and was not touched.
- **Data:** the 50 dev questions translated into lt / pl / fi / fr by `gemini-3.8-flash`, phrased as a native non-lawyer would ask, with article references in native form ("6 straipsnio 2 dalyje", "6 artiklan 2 kohdassa"). Generated once and **frozen** in `evals/retrieval_cases_ml.yaml`. Gold chunk IDs carry over unchanged, since IDs are language-independent.
- **Arms:**
  - `en_orig`: English question as is (the existing baseline);
  - `en_rewrite`: English question through the rewrite step. This is the **control**: it separates rewrite noise from the language effect;
  - `<lang>_rewrite`: translated question → guard rewrites it into English with the Act's terms → English index;
  - `<lang>_direct`: translated question embedded as is against the English index (no translation);
  - **deferred:** native search in a per-language index. It needs the other language versions of the Act, which have to be saved from a browser.
- **Rewrite prompt:** experiment-local: the production guard prompt plus a multilingual addendum (detect the language, always write the standalone question in English using the Act's terms, references in English form). The production `GUARD_SYSTEM` was **not** changed. Same guard model and thinking level as production (`gemini-3.5-flash-lite`, `minimal`).
- **Run:** `uv run --env-file .env python -m evals.multilingual_eval translate` (once), then `... run`; `run --reuse-rewrites` re-scores a retrieval-side change with the stored rewrites, so the difference is due to the change alone.
- **Results** (product retrieval; dense-only top-1 for comparison; floor = first-turn relevance floor 0.64):

| Arm | recall@1 | recall@5 | MRR | Dense-only recall@1 | Floor would block (lowest similarity) | Article-reference questions found (top 5) |
|---|---|---|---|---|---|---|
| en_orig | 0.92 | 0.98 | 0.953 | 0.78 | 0 (0.676) | 7/7 |
| en_rewrite (control) | 0.94 | 0.98 | 0.963 | 0.84 | 0 (0.768) | 7/7 |
| lt_rewrite | 0.90 | 0.98 | 0.940 | 0.84 | 0 (0.712) | 7/7 |
| pl_rewrite | 0.90 | 0.98 | 0.943 | 0.86 | 0 (0.676) | 7/7 |
| fi_rewrite | 0.88 | 0.98 | 0.933 | 0.82 | 0 (0.676) | 7/7 |
| fr_rewrite | 0.88 | 1.00 | 0.925 | 0.84 | 0 (0.705) | 7/7 |
| lt_direct | 0.88 | 0.98 | 0.916 | 0.62 | **1** (0.629) | 6/7 |
| pl_direct | 0.82 | 0.94 | 0.879 | 0.60 | **1** (0.595) | 5/7 |
| fi_direct | 0.88 | 0.98 | 0.924 | 0.60 | 0 (0.648) | 6/7 |
| fr_direct | 0.74 | 0.94 | 0.829 | 0.68 | 0 (0.669) | 6/7 |

- **Guard with the multilingual addendum** (250 calls): language detected correctly **250/250**; **0/250** in-scope questions labelled out of scope or ambiguous; $0.086 in total (≈ $0.00034 per call); p50 latency 0.73–0.84 s per language. Translating the question set cost $0.03.
- **Bug found and fixed (resolver):** the first run lost "What is listed in Annex III point 8?" in all four languages (recall@5 0.96 for lt / pl / fi). The rewrite wrote "point 8 of Annex III", and the resolver only knew the order "Annex III point 8", so it matched the annex but not the point. English users write that order too. The resolver now normalises "point N of Annex X" and "paragraph N of Article M"; two tests added. English dev retrieval is unchanged (0.92 / 0.98 / 0.953). The table shows the re-score with the same stored rewrites.
- **Bug found and fixed (concurrency, product code):** parallel guard calls failed with "client has been closed". Concurrent first calls each created a Gemini client; the extra ones were garbage-collected, and the SDK closes the HTTP connection on delete, while a request was still using it. The app runs chat requests on worker threads, so it could have hit this under load. `app/llm/gemini.py` now creates the client once under a lock; regression test `tests/test_gemini_client.py`.
- **Findings:**
  1. **Translate-first meets the 5 pp gate** on recall@5 (gap 0; French +2) and MRR (gap 2.0–3.8 pp). Recall@1 trails the control by 4–6 pp (2–3 questions). The diagnosed misses are near-ties: the gold provision ranked second, e.g. "obligations of providers of high-risk AI systems" where the only difference from the English rewrite was the words "under the AI Act". The answer model receives the top 8, so recall@5 and MRR matter more than recall@1.
  2. **Direct search is stronger than expected at recall@5** (0.94–0.98): the embedder is multilingual. But it is weaker where it counts:
     - its dense top-1 is much worse (0.60–0.68 against 0.82–0.86). In all 51 cases where the product ranking rescued it, the dense top hit was a **recital**, pushed down by the existing recital weight;
     - article-reference questions fail more often (5–6/7), because the resolver only reads English;
     - the first-turn relevance floor would **wrongly refuse** 2 of 200 in-scope questions (LT 0.629, PL 0.595).
  3. **Design implication:** for non-English input, the floor must run on the English rewrite, so the guard runs before the floor. A cheap deterministic language check can decide the order, keeping the free first-turn floor for English.
  4. Language detection and translation add no separate call: they are two more fields in the guard's existing JSON.
- **Decision:** the data supports the "English index + aligned texts" design (provisional, see caveats). Nothing in the product changes yet; multilingual is a post-MVP pilot unless decided otherwise.
- **Caveats:**
  - **Round-trip bias:** the questions were translated by `gemini-3.8-flash` and back by `gemini-3.5-flash-lite`, the same model family, which may recover the original English terms more easily than with real users' wording;
  - the translations are **not yet checked by native speakers**, and translated questions are cleaner than what real users type;
  - one run of the (non-deterministic) rewrites;
  - small set: 1 question = 2 pp;
  - the resolver fix was made after seeing dev failures, which the dev/test rule allows; a held-out multilingual set is needed for a final number.
- **Files:** `evals/retrieval_cases_ml.yaml`, `multilingual_dev.json`.

---

## Planned

- **E7 — Overhead of the gate (latency and cost)**, requested by the user. The same end-to-end question set runs through three configurations; only the gate changes.
  - **A** full gate (pre-filter, floor, guard, answer);
  - **B** no guard (the answer prompt refuses off-topic questions itself);
  - **C** no floor.
  - Measured: time to first token and total time (p50/p95); tokens and cost per step and per 100 questions at 80/20 and 60/40 in-scope/off-topic mixes; off-topic stopped and at which step; false refusals; follow-up quality.
  - Needs per-step timers in `ChatService` (not built yet).
  - Single-request estimate so far: the guard adds ≈$0.0003 and 0.6–1.0 s per in-scope question, and pays for itself when more than ~11% of the questions reaching it are off-topic (~6% from 1 Jan 2027).

- **E6 — End-to-end regex eval and model selection (Gemini vs Mistral)**, as in PLAN §3.2–3.4:
  - answers checked with must-match / must-not-match patterns;
  - citation validity;
  - refusal behaviour;
  - multi-turn cases;
  - with its own dev/test split.
  - The decision goes to `evals/results/DECISION.md`.
