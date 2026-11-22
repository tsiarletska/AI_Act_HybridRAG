# Methodology

How the EU AI Act assistant was designed, built, evaluated and validated, from the first analysis of the document to the current prototype. It covers both the **system** (what was built and why) and the **process** (how decisions were made and how AI-generated work was checked).

Detailed records live elsewhere; this file ties them together:

| Topic | Detailed record |
|---|---|
| Plan, architecture, scope policy, model-selection strategy | `docs/PLAN.md` |
| Every evaluation run, with commands and numbers | `docs/EVALUATION_LOG.md` (E1–E7) |
| Chunking assessment | `docs/CHUNKING.md` |
| Key prompt, conversation log, validation notes | `docs/CONVERSATION_LOG.md` |
| Architecture diagram | `docs/architecture.html` |
| Feasibility, risks, scalability and running cost | `docs/PRODUCTION.md` |
| Raw results | `evals/results/*.json` |

Status on 2026-11-20: milestones M0–M4 and M6 are built, and the 1,000-case end-to-end dataset and its runner are ready. Open: the end-to-end run and the Gemini vs Mistral decision (M5, waiting for Gemini credits and the user's dataset review), deployment to Railway (M7) and the final deliverables (M8). Sections marked **Planned** describe method that is designed but not yet run.

---

## 1. Principles

These rules were applied to every step and explain most of the decisions below.

1. **The source text is the only ground truth.** Gold answers, gold chunk IDs and regex patterns are found by searching the parsed text of the Act, never written from a model's memory of it.
2. **Measure, then decide.** Each component was added only if an evaluation showed it helped. Components that did not help were removed (the article-title ranker), and the evidence is kept.
3. **Decide on dev, confirm on test once.** Tuning uses a development set; a frozen test set, written before tuning, is run once per final configuration with failures not printed. A gap under 5 percentage points counts as a tie.
4. **Deterministic first, LLM last.** Anything a regex, a lookup or a threshold can do is done without a model: reference resolution, pre-filtering, the relevance floor, citation checking and the evaluation itself. Model calls are kept for what needs language understanding.
5. **Cheapest check first.** Requests pass through checks in order of cost, so an off-topic or abusive request is stopped before it reaches the expensive answer model.
6. **One code path.** The web UI and the evaluations call the same `ChatService`, so the numbers describe what users actually get.
7. **Fail loudly.** Silent auto-fixes were replaced by errors. This exposed real bugs (§10.3).
8. **State caveats next to results.** Every evaluation records its known weaknesses (leakage, small sets, home advantage) alongside its numbers.

---

## 2. Problem framing

**Assignment:** a natural-language interface prototype for questions about one EU regulation, detailed enough to discuss production feasibility, target design and effort. Required outputs: an architecture diagram, Python prototype code, the key prompts used with AI coding assistants and how their output was validated.

**Requirements set by the user** (key prompt, Turn 1):

| # | Requirement | How it is met |
|---|---|---|
| 1 | Memory and clarification questions | SQLite conversation memory; follow-ups rewritten into standalone questions; citations carried over between turns; the guard asks a clarifying question when a question is ambiguous (§6) |
| 2 | Guardrails, so tokens are not spent on unrelated chat or code | Layered gate: rate limits, regex pre-filter, embedding relevance floor, cheap guard model, grounded answer prompt, output check (§7) |
| 3 | An assessment system with a deterministic regex layer | Retrieval eval (no LLM); end-to-end eval with must-match / must-not-match regexes over answers with an enforced citation format (§8) |

**Decisions taken with the user** (Turns 2–5):
- **Corpus:** the original OJ text of 12.7.2024, as the assignment names it, in English. A consolidated version (27.07.2026) exists with later amendments; the UI shows a banner and date answers carry a note.
- **Models:** one answer model in the product, chosen between Gemini and Mistral by evaluation; a cheap model as the guard.
- **Retrieval, not the whole Act in context**, even though the Act (~125k tokens) would fit: cost per question, precise citations, focused answers.
- **Embeddings:** Gemini, confirmed by measurement (§5).
- **Frontend:** plain HTML/JS with four tabs (Chat, Source code, Evaluation, Agentic usage).
- **Deployment:** first planned on a Hugging Face Space; changed on 2026-11-19 to **Railway** (Docker from the GitHub repo, SQLite on a volume), which the user knows better.

---

## 3. Corpus acquisition and analysis

**Acquisition.** The HTML and PDF of CELEX 32024R1689 were downloaded once and stored with SHA-256 hashes in `data/raw/SHA256SUMS`, so every later build can prove it used the same text. EUR-Lex has since started returning a bot challenge to scripted downloads; it was not bypassed, and any newer version would be saved from a browser.

**Analysis** (`PLAN.md` §1). The HTML was parsed with BeautifulSoup and its structure measured:

| Part | Count | Words |
|---|---|---|
| Recitals | 180 | ~34.7k |
| Articles | 113 in 13 chapters, 509 numbered paragraphs | ~45.5k |
| Annexes | 13 | ~7.4k |
| **Total** | | ~90k words ≈ 125k tokens |

Findings that shaped the design:
- **Stable anchors** (`art_5`, `005.001` = Art. 5(1), `anx_III`, `rct_47`): chunk boundaries and citation links can follow the document exactly.
- **Very uneven unit sizes** (a definition can be 10 words; Art. 3 is 2,600 words with 68 definitions; Art. 5 is 1,800): no fixed chunk size fits.
- **Points depend on their lead-in**, and provisions rarely name their subject; the context sits in the headings.
- **Dense cross-references** ("referred to in Article 6(2)"): questions often need more than one hop.
- **Text gotchas for regex evaluation:** spaced thousands (`EUR 35 000 000`, `7 %`) and superscripts that flatten (`10^25` → `10 25`) unless kept.
- **Articles 102–110 quote paragraphs of other regulations** with foreign anchor IDs (found later by a failing uniqueness check, §10.3).

---

## 4. Ingestion and chunking

**Parser and chunker** (`app/ingest/`). A deterministic build turns the HTML into `data/processed/chunks.jsonl`: **893 chunks**. Each has a canonical ID (`art_5_1_f`), a citation label (`Art. 5(1)(f)`), a EUR-Lex anchor URL, a header (`Chapter › Section › Article title`) and its outgoing references.

Rules follow the structure of the Act:
- one chunk per article paragraph; paragraphs above ~350 words are split into points, with the lead-in repeated in each point;
- one chunk per definition in Art. 3, keyed by the defined term;
- one chunk per recital; annexes split by point or section, tiny items packed together.

**Assessment of chunking strategies** (E5, `docs/CHUNKING.md`). Asked by the user in Turn 6. Seven strategies built from the same parsed text were compared: fixed windows (250, 500 words), a recursive splitter (350), one chunk per article, one per paragraph, structural, and structural without its header.

Method choices that keep the comparison fair:
- **Strategy-agnostic gold.** Other strategies have no structural IDs, so a gold unit counts as found when ≥ 50% of its own word 5-grams (lead-in removed) are in the retrieved text.
- **Recall at a fixed context budget** (500 / 1,500 / 3,000 words), because recall@k rewards big chunks.
- **Dense-only as the primary view**, since the dev questions and BM25 tuning were built on structural chunks (home advantage); the resolver, which only structural chunks can use, was excluded.
- Offline checks before any API call: every unit's text is present in the source; lead-in stripping verified.

Result: structural chunking reaches full recall at 1,500 words on both sets (dense recall at 500 words: dev 0.94, test 0.96, against 0.42–0.90 and 0.52–0.92 for the others). At 3,000 words the strong strategies tie. Both the header and the fine splits help. **Decision:** keep the structural chunker. Halving the answer context is a hypothesis for the end-to-end eval, not a change yet.

---

## 5. Retrieval

**Design** (`app/retrieval/`). Three rankers fused with weighted Reciprocal Rank Fusion (K = 60):

1. **Reference resolver (regex).** "Article 6(2)", "Annex III point 4", "recital 47" or a defined term go straight to their units. *Exact* references are placed first; articles mentioned *in passing* get a boost. A date rule adds Art. 113 for "when does … apply / deadline / which date" questions.
2. **BM25** over chunk text, with a small lay → legal glossary ("fine" → "penalties administrative", "job" → "recruitment selection employment").
3. **Dense embeddings**, `gemini-embedding-2` (768-d) by default.

Recitals are down-weighted (×0.8). If the embedding API fails, search falls back to BM25 + resolver, and the relevance floor is skipped.

**How each piece was chosen:**

| Experiment | Question | Result | Decision |
|---|---|---|---|
| E1 Ablation (local embedder) | Which components help? | Dev recall@5 / MRR: BM25 0.66 / 0.49 → hybrid 0.78 / 0.67 → + glossary 0.82 / 0.70 → + resolver **0.94 / 0.82**. Title ranker lowered recall | Keep hybrid, glossary, resolver; drop the title ranker |
| E3 Embedder comparison | Local vs Gemini embeddings? | Recall@1 / @5 / MRR, dev: local 0.74 / 0.94 / 0.82, gemini-001 0.84 / 0.98 / 0.91, **gemini-2 0.92 / 0.98 / 0.95**; test: gemini-2 0.96 / 1.00 / 0.98 | `gemini-embedding-2` |
| E4 BM25 weight | Equal-weight BM25 hurt the strong embedder | Dev recall@1 / MRR: w=0 0.94 / 0.963, **w=0.25 0.92 / 0.953**, w=1 0.82 / 0.895 | 0.25 for Gemini (keeps exact-term matching and a warm fallback), 1.0 for local |
| A Query text (2026-11-21) | Search with the user's original message, the guard's rewrite, or both? (`evals/rewrite_retrieval_ab.py`) | 395 dev first-turn questions, run 1's own rewrites, no LLM calls. Recall@1 / @8 / MRR: original 0.719 / 0.947 / 0.803, rewrite 0.714 / 0.954 / 0.804, both 0.737 / 0.957 / 0.818. Rewrite vs original: gold ranked higher 41 vs 40 (tie). Both vs rewrite: 34 vs 20 (sign test p = 0.08) | **Keep the rewrite** (user's decision). It is needed for follow-ups and is neutral for first messages: it helps when it maps lay words to the Act's terms ("paperwork" → "technical documentation", "companies using" → "deployers") and hurts when it reframes ("doesn't fix in time" → "penalties"). "Both" is a free, not-yet-significant candidate; adopting it would need one confirming run on the frozen test split |

**API pitfalls found by smoke tests, not by reading:** `gemini-embedding-2` merges several texts sent in one request into a single vector, and ignores `task_type`. Each text is now sent in its own `Content`, with the documented prefixes (`task: question answering | query: …`, `title: … | text: …`).

**Robustness:** bulk indexing retries with backoff; a query gets one fast retry, only on 429/5xx, so the fallback starts within about a second. Chunk vectors are cached per (chunks-file hash, embedder), so the deployed app uses exactly the evaluated vectors.

---

## 6. Answer generation and memory

**Models** (verified against the provider's model list and pricing page on 2026-11-18, not from memory):
- Answer: `gemini-3.8-flash`, thinking `low`, no temperature (deprecated for Gemini 3.x), 2,048 output tokens. Mistral is the second candidate, pending its key.
- Guard: `gemini-3.5-flash-lite`, thinking `minimal`, JSON-schema output. Chosen over 3.1-flash-lite after a smoke test: 0 thinking tokens and 0.6–1.0 s.
- **Why `gemini-3.8-flash` and not `gemini-3.5-flash-lite` for answers** (user's decision, 2026-11-20): the multilingual version (§8.4) is still intended if time allows, and in the user's professional experience 3.8 Flash handles translation and multilingual context better, while 3.5 Flash-Lite is good at summarising and rewriting (hence its role as guard and rewriter). The choice rests on that experience, not on a measurement in this project; the end-to-end eval measures 3.8 Flash's answers, and a multilingual comparison would test the claim.
- **Mistral comparison run (run 2, 2026-11-20):** `mistral-large-4` replaces only the answer model. The guard/rewriter (`gemini-3.5-flash-lite`), the embedder, retrieval, the floor, the prompts and the Legal detail style stay the same, so differences in the answer path come from the answer model. Provider facts checked by smoke tests rather than assumed: Large 4 always reasons (`reasoning_effort` accepts only low/medium/high; "none" returns a 400), so it runs at "low", the same level as the Gemini answer model. Reasoning arrives as hidden chunks in the stream and is filtered out, and reasoning tokens are billed as output. Price $0.70/$2.10 per 1M tokens. Caveat: the guard is not deterministic, so a few borderline cases take a different path (answer vs guard refusal) between runs. The model comparison is therefore made on cases both runs answered, with path differences reported separately.
- **Reasoning-matched Gemini run (run 3, 2026-11-20, user's request for an equal comparison):** a probe through the real pipeline (3 smoke questions, same prompt and excerpts) showed `gemini-3.8-flash` at thinking `low` uses 0 thinking tokens, while `mistral-large-4` cannot go below `low` (346-668 thinking tokens). Gemini `medium` (644-1,061) is the closest available match (`high` 749-1,338). Run 3 repeats run 1 with `ANSWER_THINKING=medium`, everything else unchanged (file tag `think-medium`), so runs 2 vs 3 compare the providers with reasoning on, and runs 1 vs 3 show what reasoning adds for Gemini. A no-reasoning Mistral (`mistral-medium-3-5`, 0 reasoning tokens) remains the option for a match against run 1. Runs 2 and 3 ran at the same time for part of their duration, against different answer providers; the shared guard and embedding calls may add a little latency to both.
- **Results of runs 1-3 (2026-11-20; 676 cases answered in all three runs; Sonnet judge; Legal detail):**

  | | Gemini, no reasoning (run 1) | Gemini, medium (run 3) | Mistral Large 4, low (run 2) |
  |---|---|---|---|
  | Judge overall | 9.12 | 9.09 | 9.13 |
  | Correctness / completeness | 9.52 / 9.15 | 9.48 / 9.16 | 9.50 / 8.90 |
  | Grounding / citations / clarity | 9.65 / 9.57 / 9.06 | 9.63 / 9.55 / 9.02 | 9.71 / 9.64 / 9.35 |
  | Deterministic pass (shared cases) | 592 | 605 | 611 |
  | Expected facts found | 614 | 611 | 601 |
  | Answer model, first token p50 / p90 / max | 1.8 / 2.2 / 67 s | 6.3 / 10.0 / 19 s | 6.8 / 26.2 / 103 s |
  | Answer cost, 1,000 cases | $1.79 | $3.46 | $1.98 |

  Reasoning brought no measurable quality gain, for either provider. Case by case, Gemini medium beat Gemini low on 123 cases and lost on 126, a symmetric spread that looks like judge and sampling noise. The higher deterministic pass rates of runs 2 and 3 come from `citations_valid`, the check suspected of being too strict, not from facts (where Gemini without reasoning is highest). Mistral writes shorter, clearer answers that leave out more. Decision basis: Gemini 3.8 Flash without reasoning gives the same quality at about a quarter of the time to first word and half the cost of either reasoning setup. The first-token times are the answer model alone; for the selected setup, the user waits 3.3 s median and 4.1 s p95 for the first word, including the floor, guard and retrieval.
- Prices are kept with effective dates in `app/pricing.yaml`; cost is computed from the token usage the API returns.

**Prompts** (`app/chat/prompts.py`):
- **Guard prompt:** one call both rewrites the new message into a standalone question (resolving "and deployers?") and labels it `in` / `out` / `ambiguous`, with a clarifying question for `ambiguous`. A comparison with another law counts as in scope (AI Act side only).
- **Answer prompt**, seven rules: use only the numbered excerpts; cite every statement by copying the excerpt label in square brackets; never invent article numbers; direct answer first; prefer articles over recitals; never write code; add "not legal advice" for personal situations; note that later amendments are not reflected for dates.

The fixed citation format `[Art. 99(3)]` is what makes deterministic checking possible: it can be parsed, validated against the retrieved set and matched by regex.

**Memory** (`app/chat/memory.py`). SQLite stores every turn with its role, text, rewritten standalone question, kind (answer / refusal / clarification / error), cited chunk IDs, usage, cost and sources. The last 4 turns go to the guard and the answer model; sessions are capped at 30 turns. The chunks cited in the previous answer are added to the next turn's candidates (citation carry-over), so a follow-up keeps its context even if retrieval drifts.

**Post-check** after each answer: code fences removed, citations checked against the retrieved set (a citation that narrows a retrieved excerpt, such as `[Annex III, point 1(c)]` from `Annex III, point 1`, is valid), missing citations and truncation flagged. The streaming UI shows issues as badges (tokens are already on screen, so it cannot retry); the non-streaming path used by the evals retries once with feedback.

---

## 7. Guardrails

Ordered from cheapest to most expensive (`app/chat/pipeline.py`):

| Step | Check | Cost | Stops |
|---|---|---|---|
| 0 | Rate limits: 8/min and 100/day per client, 1,500/day globally; 30 turns per session; 2,000-character input cap | none | abuse, runaway spend |
| 1 | Regex pre-filter: code requests, code blocks, known injection phrases | none | "write a Python script…" |
| 2 | Relevance floor on the first turn: best dense similarity < 0.64 | one embedding | clearly off-topic (weather, recipes) |
| 3 | Guard model: rewrite + classify | cheap LLM | near-domain off-topic (GDPR alone, US policy); ambiguous → clarifying question |
| 4 | Relevance floor on the rewritten follow-up | (same embedding as retrieval) | off-topic follow-ups |
| 5 | Grounded answer prompt | answer LLM | out-of-excerpt claims, code |
| 6 | Output post-check | none | invalid citations, code fences |

**Calibration rather than guessing:**
- **Relevance floor (E2):** set by one rule, the lowest in-scope dev similarity minus 0.03 (0.64 for gemini-embedding-2). It blocks 13/15 clearly off-topic questions and 0/50 dev questions; checked once on the frozen test set as a count: 0/25 blocked. It is applied to the raw question only on a first turn, and to the rewritten question on follow-ups, because a raw "and deployers?" scores low.
- **Pre-filter:** written narrowly, with negative tests for in-scope wording. A review found false refusals ("a compliance checklist for my app", "the risk class of", "the function of the AI Office"); the noun list is now code-specific only.
- **Fail-open guard:** if the guard call fails, the question is treated as in scope; the floor and the answer prompt still constrain it.

**Browser check (E6):** a code request was stopped by the pre-filter (0 API calls); weather by the floor (similarity 0.525, 0 LLM calls); a GDPR question passed the floor (0.645) and was refused by the guard (one cheap call, no answer-model call).

**Does the guard pay for itself?** From single requests: the guard costs ≈ $0.0003 and 0.6–1.0 s per in-scope question and saves ≈ $0.0025 each time it stops one. It breaks even above ~11% off-topic traffic reaching it (~6% after the answer-model price rise on 1 Jan 2027). Its main cost is latency. Experiment E7 (§8.5) will measure this properly.

---

## 8. Assessment system

### 8.1 Two deterministic layers

| Layer | What it checks | LLM? | Status |
|---|---|---|---|
| **Retrieval eval** | Is the gold chunk among the retrieved ones? recall@k, MRR | no, free | built, runs on every change |
| **End-to-end regex eval** | Does the answer contain the right facts and citations, and nothing it must not? | yes (answer model) | dataset and runner built; full run pending (M5) |

### 8.2 Datasets

- **Retrieval:** dev 50 questions (43 natural-language, 7 naming an article), test 25 questions written before any tuning and frozen (`evals/retrieval_cases*.yaml`). Gold labels are chunk IDs found by phrase search over the parsed text.
- **End-to-end (`evals/e2e_cases.yaml`, built, frozen): 1,000 English cases, 700 dev / 300 test.** Categories: provision 393, definition 61, scenario 54, rare term 60 (terms found in at most two chunks, e.g. CCTV), multi-turn 60, not in the Act 30, ambiguous 40, off-topic 122, code 60, injection 120. Generated by `gemini-4-hydrogen` (`evals/build_e2e_dataset.py`, $5.36): each in-scope case comes from one source chunk (two for follow-ups), so its gold provision is known; every required fact was checked to appear verbatim in that chunk; questions copying 5+ consecutive words from their chunk were dropped; near-duplicates removed. **Caveat:** the generator is a stronger model of the same family as the answer model. A 30-case sample was read by the agent (three injection regexes fixed that would have matched the app's own refusal); the full set is under review by the user (`evals/e2e_cases_review.csv`) before the run. Each case has `must_match` and `must_not_match` regexes, e.g. `35\s?000\s?000|35\s?million`, `7\s?%`, `\[Art\. 99\(3\)\]`; text is normalised (whitespace, spaces inside numbers, quotes, dashes) before matching. The runner (`evals/run_e2e.py`) uses the UI's streaming path, keeps API errors apart from model failures and writes one CSV row per case (question, answer, gold, every check, models, tokens, cost, per-step timings, empty judge and human columns).

### 8.3 Experiments run so far

| ID | Experiment | Outcome |
|---|---|---|
| E1 | Retrieval ablation | hybrid + glossary + resolver; title ranker rejected |
| E2 | Relevance floor calibration | floor per embedder; 13/15 off-topic blocked, 0/50 dev, 0/25 test |
| E3 | Embedder comparison | `gemini-embedding-2` |
| E4 | BM25 fusion weight | 0.25 for Gemini embedders |
| E5 | Chunking strategies (7) | structural chunker kept |
| E6 | Manual browser check | 3 bugs found and fixed (Art. 113 for dates, narrowed citations, dropped message) |
| E9 | First end-to-end run (Gemini) | Aborted: the prepaid Gemini credits ran out (`402 RESOURCE_EXHAUSTED`); only 77 of 1,000 cases completed (62 dev, 15 test, many of them pre-filter refusals that need no API call); the 923 failures were recorded as infrastructure errors, not model failures. No conclusions drawn. Caveat: 15 test-set results were printed, a minor exposure to disclose. To be re-run after the dataset review |
| E8 | Multilingual retrieval (lt, pl, fi, fr; dev) | Translate-to-English-then-search matches English at recall@5 (0.98–1.00) and within 4 pp on MRR; searching untranslated questions is weaker at top-1, misses article references and trips the floor. Supports one English index plus aligned texts (provisional) |

Product retrieval with `gemini-embedding-2`: recall@1 / @5 / MRR dev 0.92 / 0.98 / 0.953, test 0.96 / 1.00 / 0.98. The test set is now saturated and can no longer separate later retrieval changes; the end-to-end eval gets its own split.

### 8.4 Multilingual design (post-MVP, not in the deadline scope)

Five languages are planned: English, Lithuanian, Polish, Finnish, French. The Act exists in 24 equally authentic language versions with the same structure, so chunk IDs and EUR-Lex anchors are shared across languages. The design keeps **one English index**: the guard detects the language and rewrites the question into English with the Act's terms; retrieval runs as today; the excerpts are then swapped for the official text of the same chunk IDs in the user's language, and the answer is written in that language. Adding a language means parsing its text and translating the test questions, with no new index. E8 tested the retrieval half of this on dev; the text alignment, answers and native-speaker review are still to do. The off-topic floor must run on the English rewrite for non-English input (E8, finding 3).

**Answer style toggle (built).** The chat has a **Legal detail** (default) / **Plain language** switch. The style comes from the toggle, not from a model; only rule 3 of the answer prompt changes (`app/chat/prompts.py`, `STYLES`), and "legal" is the original prompt text, so earlier results stay valid. Plain mode asks for a short direct answer, at most four bullets, about 150 words, everyday words, each defined term explained once, and never dropping a condition, exception, date or amount. First spot checks: the same citations and exceptions in both styles; plain answers of 101–142 words on simple questions, longer where the question has many conditions. **Planned style test:** all 1,000 cases run in each style (paired, rather than a 500/500 split), so every difference is attributable to the style. Facts and citations must not drop and exceptions must survive (deterministic checks); plain answers must be measurably easier to read (readability and jargon counts); a blind judge and human comparison on 100 + 100 answers. **Run (2026-11-21, user's decision):** Gemini 3.8 Flash (thinking low) only; Mistral and Gemini medium are not repeated, since they are not selected. The judge prompt was made style-aware (each case states its intended style; for plain, clarity means a non-lawyer understands it, and a condition said in simpler words counts as present, a dropped one as missing). On the 13 Legal smoke cases, the new prompt changed 7 grades by +1. For a symmetric comparison, the Legal run is therefore re-graded with the same prompt (files tagged `judgev2`) instead of reusing its original grades. Re-grading showed the judge's own variation: about 20% of overall grades change between two gradings of the same answer (old prompt 9.16, new 9.12), so run differences under about 0.1 are noise.

**Style test result (run 4, 2026-11-21; 683 cases answered in both styles; same model, same judge prompt).** The toggle label was renamed from "Plain language" to "Explanatory" (internal key `plain` unchanged).

| | Legal detail | Explanatory |
|---|---|---|
| Judge overall | 9.00 | 8.54 (better on 82 cases, worse on 315) |
| Correctness / grounding | 9.46 / 9.65 | 9.11 / 9.27 |
| Completeness / citations | 9.03 / 9.53 | 8.81 / 9.27 |
| Clarity (judged against each style's own aim) | 9.05 | 8.16 |
| Expected facts found | 615 | 599 (17 lost, 1 gained) |
| Words, median / words per sentence | 127 / 22.7 | 119 / 20.6 |
| Flesch reading ease (higher = easier) | 19 | 25 |
| Legal-jargon phrases per answer | 1.15 | 0.16 |
| Citations per answer, median | 5 | 6 |
| TTFT p50 / answer cost | 3.3 s / $1.79 | 3.3 s / $1.74 |

Reading: the explanatory prompt removes legal jargon but does not make answers much simpler. They stay near the Legal length, still read as "very difficult" (Flesch 25), and carry even more inline citations. The judge's reasons for lower clarity name dense or long bullets, more than four bullets, and running past about 150 words. Paraphrasing also costs accuracy: correctness and grounding drop by about 0.35 points (comparable across styles, unlike clarity), and 17 answers lose an expected fact. Decision: Legal detail stays the default; the explanatory prompt needs another iteration (fewer inline citations, enforced bullet and length limits, keep the exact legal term next to its explanation) tested on a dev sample before any new full run.

### 8.5 Planned experiments

**E7, overhead of the gate** (requested by the user, Turn 8). The same end-to-end question set runs through three configurations, and only the gate changes:
- **A** full gate (pre-filter, floor, guard, answer);
- **B** no guard (the answer prompt has to refuse off-topic questions itself);
- **C** no floor.

Measured: time to first token and total time (p50 / p95); tokens and cost per step and per 100 questions at 80/20 and 60/40 in-scope/off-topic mixes; how many off-topic questions are stopped and at which step; false refusals; follow-up quality. Per-step timers are now recorded in `ChatService` (pre-filter, floor, guard, retrieval, time to first token, total) and written to the end-to-end CSV; a latency run sends one case at a time, and the deployed URL will be measured with a script, including cold start.

**Model selection, Gemini vs Mistral** (`PLAN.md` §3.4). A controlled comparison: identical retrieval (cached per question), the same guard and rewriter, the same prompt and token cap, each provider's recommended sampling settings, each case run 3 times.

| Metric | Weight |
|---|---|
| Answer correctness (all must-match hit, no must-not-match) | 0.40 |
| Citation quality (precision and recall) | 0.25 |
| Behaviour ("not in the Act", clarifications, no code) | 0.15 |
| Format compliance (parseable citations, no retry needed) | 0.10 |
| Efficiency (p95 latency, cost at January 2027 prices) | 0.10 |

Hard gates: out-of-scope/code refusal ≥ 95%, false refusals ≤ 5%, citation precision ≥ 90%. A gap under ~5 pp is a tie, broken on cost, then latency. The guard model is compared separately on refusal precision/recall and false-refusal rate. The decision goes to `evals/results/DECISION.md` and the Evaluation tab.

**Known limit:** regexes check that key facts and citations are present, not full faithfulness. An LLM judge and human review on a sample are the next step.

**LLM judge** (`evals/judge_e2e.py`, decided with the user on 2026-11-20). **Claude Sonnet 5.5**, thinking off, grades every case of a run: five aspects (correctness, completeness, grounding, citations, clarity; 1-10, empty when not applicable, e.g. refusals), an overall score from 0 (worst) to 10 (perfect) and a one-line reason written before the scores. It sees the question, the gold provision text, the retrieved excerpts and the answer, and is told to judge against them, not against its own memory of the Act. Graded through the Batch API (about $3 per 1,000 cases). An Opus 5.5 re-grade of 100 cases was planned as an agreement check and dropped by the user (2026-11-20); the user's own scores on a sample (`your_score`) are the check on the judge and the final reference.

Why a Claude judge and not a (possibly stronger) Gemini model. Whether Sonnet 5.5 is stronger than the answer model was not measured; it was not the deciding factor:
1. **Self-preference.** Models tend to rate answers in their own family's style higher. The answers (`gemini-3.8-flash`) and the dataset (`gemini-4-hydrogen`) are already Gemini; a Gemini judge would make the whole chain one family.
2. **A fair Gemini vs Mistral comparison.** The same judge must grade both providers; a Gemini judge would tilt that comparison towards Gemini, while Claude is neutral to both.
3. **Capability is checked directly instead of assumed.** The judge does not answer from memory; it compares an answer with the gold text and excerpts, which is easier than answering. Whether it is good enough is measured against the user's scores on a sample (and, optionally, deliberately broken answers it must catch); the Opus agreement check was dropped by the user. If it falls short, the fallback is Opus 5.5 as judge, which keeps the independence.

Why thinking is off for the judge: thinking tokens are billed as output and would roughly double or triple the judge cost; the task is mostly comparison against given text; the reason is written before the scores. The risk is missing subtle errors on hard cases (multi-hop, exceptions, partly supported claims). With the Opus check dropped, this risk is checked only through the user's review: if the user finds problems Sonnet scored 9-10, those categories are re-graded with thinking on.

**Blind human review (2026-11-21, the user; `evals/make_blind_review.py`, `evals/analyze_blind_review.py`).** 100 dev cases that all three generation runs answered, three answers per case in shuffled A/B/C order without model names, each scored 0-10 by the user; 99 cases scored (297 answers). Results are in `evals/review/blind_review_100_results.json`.

| | Gemini low (selected) | Gemini medium | Mistral Large 4 |
|---|---|---|---|
| Human mean | 8.82 | 8.99 | 9.05 |
| Sonnet mean, same answers | 9.13 | 9.11 | 8.95 |

- **The human ranks the setups in the opposite order to the judge.** Case by case, Mistral beat Gemini low 45 times and lost 27 (27 ties; sign test p = 0.044), Gemini medium beat Gemini low 34-22 (p = 0.14), Mistral vs Gemini medium 41-30 (p = 0.24). With three comparisons, none is significant after a Bonferroni correction (0.044 x 3 = 0.13), so this is a lead, not proof. It is consistent with the judge's higher clarity for Mistral's shorter answers, so the human appears to weigh concise, clear answers more than the judge's overall score does.
- **Judge-human agreement per answer is weak.** Pearson 0.09, Spearman 0.14; 96 of 297 exact, 223 within 1 point; the judge is higher on 136 and lower on 65 (mean 9.06 vs 8.95). Restricted to questions that expect an answer: Pearson 0.12, judge 9.25 vs human 8.96. Both score almost everything 8-10, which limits correlation, but the judge cannot be trusted to rank good answers against each other.
- **The largest gaps are labels, not answers.** Ambiguous questions expected to get a clarifying question ("Do we need a quality management system?", "Is our model general-purpose?") were answered with conditional, cited answers; the judge, following the label, scored them 2-3, and the user 8-10. Similarly an "off-topic" question about open-source AI, which the Act addresses through its open-source exemptions, was answered well (judge 3, user 9). The low "ambiguous" scores in every run therefore partly reflect strict labels: a conditional answer that states the conditions should also count.
- **Consequences.** The judge stays useful for catching behaviour failures and for large differences, not for choosing between near-equal setups. The generation choice is a trade-off the user decides: Gemini low is preferred on latency (TTFT 1.8 s vs 6.8 s for Mistral, with no long tail) and cost; Mistral may be slightly better liked. The human preference for concise answers also informs the explanatory-prompt rework.

---

## 9. Engineering

**Stack:** Python 3.12 with `uv`; FastAPI with Server-Sent Events; plain HTML/CSS/JS frontend (no build step); SQLite; `google-genai`; `rank_bm25`; optional local `fastembed`.

**Structure:** `app/ingest` (parser, chunker), `app/retrieval` (resolver, BM25, embedders, fusion), `app/llm` (one provider interface), `app/chat` (pipeline, prompts, citations, memory), `app/guards` (pre-filter, rate limiter), `app/api.py`, `app/web/`; evaluation scripts in `evals/`, tests in `tests/`.

**Tests: 90 unit tests, all passing** (`uv run pytest`). They cover:
- corpus integrity: 113 articles, 180 recitals, 13 annexes, 68 definitions; every article word present in its chunks; labels, anchors, superscripts, cross-references;
- the resolver (exact vs passing references, the date rule with positive and negative cases);
- embedder retry policy with a fake client;
- guards: pre-filter positives and in-scope negatives, rate limiter, citation variants and narrowing;
- the pipeline with fake LLMs: no LLM call on pre-filter and floor refusals, clarification, streaming and memory, follow-up rewrite and carry-over, code-fence removal, the retry path, guard fail-open, and 40 parallel retrievals for thread safety;
- Markdown rendering of the docs.

**Security for a public URL:** model text is always HTML-escaped; citation links are built from server data; the source viewer serves a fixed allow-list, never a client path; API keys only in `.env`, never committed. The rate limiter's per-IP key uses `X-Forwarded-For`, which a client can forge; the global daily cap and provider spend limits are the real protection, and the header trust is fixed at deployment on Railway (M7).

---

## 10. AI-assisted development

The project was built with an AI coding agent (Claude Code). The full log, with the user's messages verbatim, is `docs/CONVERSATION_LOG.md`.

### 10.1 Working pattern

Each turn followed the same loop:
1. **User sets direction** (requirements, decisions, questions); the agent asks back when a choice is genuinely the user's (provider, corpus version, deployment names).
2. **Orient before building:** read the source, list available models through the API, read provider docs and pricing, run smoke tests.
3. **Review before committing to a method:** a second, stronger model reviewed the approach at checkpoints (e.g. the chunking evaluation design, the build order).
4. **Build with tests**, then **measure** with the evaluation scripts.
5. **Review the result** before reporting it, and record it in the plan and logs.

### 10.2 Key prompts

- **The key prompt** (Turn 1) set the three requirements: memory and clarification, guardrails against token waste, a deterministic regex-based assessment system.
- Follow-up prompts set the model strategy (one answer model chosen by evaluation, a cheap guard), the corpus (original text), embeddings (Gemini), the chunking assessment, the interface, and the guard-overhead experiment.
- The product prompts themselves (guard and answer) are in §6 and `app/chat/prompts.py`.

### 10.3 How AI-generated output was validated

AI-generated code and write-ups were not accepted on trust:

| Practice | Example of what it caught |
|---|---|
| Facts from the source text only | Gold fines (Art. 99(3)–(5)) and dates (Art. 113) taken from phrase searches |
| Fail loudly instead of auto-fixing | Making duplicate chunk IDs raise an error exposed the Articles 102–110 parser bug that a lenient test had hidden |
| Smoke-test provider APIs before relying on them | `gemini-embedding-2` merging batched texts and ignoring `task_type` |
| Ablation instead of one number | The title ranker was measured and rejected |
| Dev/test discipline | A resolver tweak made after test misses were visible was reverted, and the test set frozen; leakage is disclosed (test viewed three times in E1) |
| Calibrated thresholds | Relevance floor and BM25 weight set by stated rules on dev |
| Independent review of write-ups | Three overstatements in the first chunking write-up corrected ("best at every budget" was false at 3,000 words; a dev-only figure presented as general; a metric artifact used as a tie-break) |
| Independent review of code | Shared search state between concurrent users; pre-filter false refusals; the date rule firing on conditional "when"; a ~30 s retry stall before fallback; the forgeable rate-limit key |
| Evaluation runs as bug finders | E8 exposed a resolver gap for "point 8 of Annex III" (affecting English users too) and a race that closed the shared Gemini client under concurrent calls |
| Real browser check, not only tests | Four bugs the unit tests missed: Art. 113 missing for date questions, narrowed citations flagged invalid, a message dropped while streaming, Markdown lists not rendering |

Each bug found was fixed with a test where possible.

---

## 11. Timeline

| Date | Turn | Step |
|---|---|---|
| 2026-11-17 | 1 | Document analysis, plan, corpus saved with hashes |
| 2026-11-18 | 2–3 | Decisions: providers, frontend, deployment, original corpus, one answer model chosen by evaluation, model-selection strategy |
| 2026-11-18 | 4 | M0–M1: parser, structural chunker, hybrid retrieval, retrieval eval (E1), relevance floor (E2) |
| 2026-11-18 | 5 | Gemini embeddings compared and adopted (E3), BM25 weight tuned (E4), fallback and retry policy |
| 2026-11-18 | 6 | Chunking strategies assessed (E5) |
| 2026-11-18 | 7 | Evaluation log; LLM layer, guard, memory, API, four-tab web app; browser check (E6) and fixes |
| 2026-11-19 | 8 | Architecture scheme; guard-overhead experiment (E7) planned |
| 2026-11-19 | 9 | This methodology |
| 2026-11-19 | 10–11 | Guard role reviewed; multilingual design (one English index plus aligned texts); plain-language toggle designed |
| 2026-11-19 | 12 | E8 multilingual retrieval experiment; two bugs fixed |
| 2026-11-19 | 13–14 | Multilingual flow added to the architecture page; end-to-end test design discussed |
| 2026-11-19 | 15 | Scope set to English for the deadline; answer style toggle built |
| 2026-11-19 | 16 | 1,000-case end-to-end dataset, runner and per-step timers; first run aborted when credits ran out (E9) |
| 2026-11-19 | 17 | Paired style test designed; deployment moved to Railway; interface redesign |
| 2026-11-20 | 18 | Methodology brought up to date |

---

## 12. Limitations and open items

- **Original text only:** application dates may be outdated by the 2026 amendments; flagged in the UI and in date answers. Keeping the corpus current is a production requirement.
- **Small retrieval sets** (50 / 25): 1 question = 2 / 4 pp; the retrieval test set is saturated. The end-to-end set (700 / 300) is large enough to separate configurations, but it is model-generated (see §8.2).
- **Regex evaluation measures presence, not faithfulness.**
- **End-to-end results come from single runs.** Each of the four 1,000-case runs was answered and graded once. Re-grading the same answers changed about 20% of the judge's overall grades, so differences between setups under about 0.1 points are within the judge's own variation; the blind human review (100 cases, one reviewer) is the only independent check.
- **Mistral is evaluated but not used in the app.** `mistral-large-4` was compared in run 2; the provider exists (`app/llm/mistral.py`), but the app runs on Gemini.
- **A failed post-check does not regenerate the answer.** After the checker fix (2026-11-21: comma-joined, shorthand, range, dotted and parent-paragraph citation forms; 9 new tests), answers with an unverified citation fell from 7.6% to 0.4% in run 1 (Gemini with reasoning and Mistral: 0). The remaining genuine cases are marked in red at the citation, using the server's per-citation verdict, but the answer is not blocked or regenerated.
- **No mechanism to improve the system from user feedback.** Users cannot rate an answer or report a problem, and nothing they do feeds back into the prompts, the retrieval or the evaluation set; quality is known only from the offline evaluations. A feedback box and per-answer ratings were proposed but not built (PLAN §8, item 3).
- **Multilingual designed, not built.** The design and a first retrieval experiment (E8) exist; building and validating five languages went beyond the project's time and budget.
- **Deployment:** live on Railway since 2026-11-22 (https://aiacthybridrag-production.up.railway.app), one container, no volume, so stored conversations are reset on every redeploy. Checked live: the rate limit counts per visitor (after more than 8 requests within a minute, further ones are refused), and a client-sent `X-Real-IP` or `X-Forwarded-For` header did not get around it, because Railway's proxy sets `X-Real-IP` itself.

---

## 13. Reproducing the results

```bash
uv sync
uv run pytest                                                         # 90 unit tests
uv run python -m app.ingest.chunker                                   # rebuild chunks (if needed)
uv run --env-file .env python -m evals.run_retrieval_eval --embedder gemini2
uv run --env-file .env python -m evals.run_retrieval_eval --embedder gemini2 --cases evals/retrieval_cases_test.yaml
uv run --env-file .env python -m evals.calibrate_floor --embedder gemini2
uv run --env-file .env python -m evals.sweep_bm25_weight
uv run --env-file .env python -m evals.chunking_eval
uv run --env-file .env python -m evals.multilingual_eval run          # E8 (translations are frozen)
uv run --env-file .env uvicorn app.api:app --port 7860                # the app
```

`GEMINI_API_KEY` goes in `.env`. Results are written to `evals/results/`.
