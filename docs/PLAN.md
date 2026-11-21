# EU AI Act RAG Chatbot — MVP Plan

Source: Regulation (EU) 2024/1689 (the "AI Act"), CELEX 32024R1689, original OJ text (https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng).
Scope of the MVP: English only, one document. A public web app with four sections: chat, source code, evaluation results, and agentic usage.

### Assignment frame
Build a natural language interface prototype for questions about one EU regulation (the AI Act). The prototype must be detailed enough to answer questions on **feasibility of a production system**, **design of the target solution** and **effort estimation**. Required outputs:

| Required output | Where |
|---|---|
| Solution architecture diagram (draw.io) with components, inputs and outputs | `docs/architecture.drawio` (+ exported SVG shown in the "Source code" tab) |
| Prototype code in Python (.py and/or .ipynb) | `app/` (.py) + `notebooks/walkthrough.ipynb` (end-to-end demo) |
| Key prompts used with AI coding assistants + how the output was validated | `docs/CONVERSATION_LOG.md` + "Validation" section; "Agentic usage" tab |
| Feasibility / target design / effort estimation | `docs/PRODUCTION.md` |

Decisions taken (2026-11-18), see `docs/CONVERSATION_LOG.md`:

| Topic | Decision |
|---|---|
| Answer model | **One** answer model in the product. **Gemini vs Mistral is decided by the evaluation**; the winner becomes the default |
| Guardrail model | A **cheap** model (candidates: Gemini Flash-Lite, Ministral), also chosen by evaluation |
| Corpus | **Original OJ text** (12.7.2024), as named in the assignment |
| Frontend | Plain **HTML/JS** with 4 sections: Chat · Source code · Evaluation (dedicated results page) · Agentic usage |
| Deployment | **Hugging Face Spaces** (Docker) first; fallback GitHub Actions + **Railway**. Public link required |
| Citations | Links to article/paragraph anchors on EUR-Lex. Page numbers not needed |
| Conversation log | `docs/CONVERSATION_LOG.md` holds the key prompt and the log of this conversation |
| Answer style (2026-11-19) | A UI toggle, **Legal detail** (default) / **Plain language**. The style comes from the toggle, not from a model; only the style rule of the answer prompt changes, the grounding rules are identical |
| Deployment (2026-11-19) | **Railway** instead of the HF Space (the user knows it better). Docker deploy from the GitHub repo; SQLite on a Railway volume; app listens on `$PORT` |
| Scope for the deadline (2026-11-19) | **English only.** The multilingual design (one English index + aligned official texts, E8) is documented as a post-MVP option, built only if time allows |

---

## 1. Document analysis

Analysed from the EUR-Lex HTML of the original OJ text (`data/raw/aiact.html`, sha256 in `data/raw/SHA256SUMS`) and the PDF (144 pages).

| Part | Count | Words | Notes |
|---|---|---|---|
| Recitals | 180 | ~34.7k | Explain intent ("why"). Not binding but useful for interpretation |
| Articles | 113 (13 chapters, sections in Ch. III, V, VII, IX) | ~45.5k | 509 numbered paragraphs. Binding text |
| Annexes | 13 (I–XIII) | ~7.4k | Lists: high-risk use cases (III), technical docs (IV, XI), GPAI systemic-risk criteria (XIII)… |
| **Total** | | **~90k words ≈ 120–130k tokens** | Small corpus: ~1–1.5k chunks |

Largest articles: Art. 3 Definitions (2.6k words, **68 definitions**), Art. 5 Prohibited practices (1.8k), Art. 57 Sandboxes, Art. 60 Real-world testing, Art. 26 Deployer obligations.

### HTML anchors we chunk on

| Anchor | Meaning | Example |
|---|---|---|
| `rct_N` | Recital N | `rct_47` |
| `cpt_X`, `cpt_X.sct_N` | Chapter / section | `cpt_III.sct_2` |
| `art_N` (+ `.oj-sti-art` title) | Article N | `art_5` → "Prohibited AI practices" |
| `NNN.PPP` | Article N, paragraph P (**verified**: `005.001` = Art. 5(1), `099.003` = Art. 99(3)) | `006.002` |
| `anx_X` | Annex X | `anx_III` |

### Gotchas (matter for parsing and regex evals)
- Amounts use spaces as thousands separators (`EUR 35 000 000`, `7 %`).
- Superscripts flatten badly (`10^25` FLOPs becomes `10 25`), so the parser must keep `<sup>`.
- Points are nested (`Art. 5(1)(a)`, `Annex III point 4(a)`).
- Cross-references are frequent ("referred to in Article 6(2)"), so questions often need more than one hop (Art. 6 → Annex III → Art. 8–15).
- Footnotes point to other EU acts that are not in the corpus.

### Document version (decision: original text)
- The prototype uses the **original OJ text (12.7.2024)**, as the assignment specifies.
- EUR-Lex also has a **consolidated version dated 27.07.2026** (`CELEX 02024R1689-20260727`), which includes the "Digital Omnibus on AI" amendments. Per secondary sources, these postpone the high-risk deadlines (Annex III → 2 Dec 2027, Annex I → 2 Aug 2028).
- Consequence: answers about **application dates may be outdated**. The UI shows a banner ("Based on the original text of Regulation (EU) 2024/1689 as published in OJ L, 12.7.2024; later amendments are not reflected"). For date questions, the system prompt adds a short note that the Act was amended.
- In production, keeping the corpus up to date (detecting new consolidated versions and re-indexing) is a core requirement. See `docs/PRODUCTION.md`.

---

## 2. Architecture

```
  Browser (static HTML/JS, 4 tabs) ──► FastAPI (one container on HF Spaces)
                                         │
   /api/chat (SSE)                       │
     1. Input guard (deterministic): length cap, rate limit, regex for code/injection
     2. Scope classifier (Gemini Flash-Lite, JSON output): in_scope | out_of_scope | ambiguous
        (+ optional Mistral Moderation 2 jailbreak check)
     3. Query rewriter (Flash-Lite): follow-up + history → standalone query
     4. Retrieval: reference resolver (regex) + BM25 + embeddings → RRF fuse → top-k
          └─ score floor → ask a clarification question or say "not covered"
     5. Answer LLM (one configured model; Gemini or Mistral, picked by the evaluation): system prompt + chunks + recent history
     6. Output guard: citation present & valid (⊆ retrieved IDs), no code blocks
     7. Persist turn (SQLite): messages, cited IDs, token usage, guard decisions
   /api/eval      → latest eval results (JSON committed in evals/results/)
   /api/docs/...  → PLAN.md, CONVERSATION_LOG.md rendered for the Agentic usage tab
```

### 2.1 Ingestion (`app/ingest/`)
- BeautifulSoup parses the HTML into `data/processed/chunks.jsonl`.
- Chunks follow the document's structure:
  - **Article paragraph**: one chunk per paragraph, with metadata `{chapter, section, article, article_title, paragraph}`.
  - **Art. 3**: one chunk per definition (68), keyed by the defined term.
  - **Long paragraphs** (e.g. Art. 5(1)): split by point (a), (b)… when longer than ~400 tokens, with the paragraph's lead-in sentence prefixed.
  - **Recitals**: one chunk each. **Annexes**: by numbered point or section.
- Each chunk has a canonical ID (`art_5_1_a`, `anx_III_4`, `rct_47`), a label (`Art. 5(1)(a)`), a EUR-Lex URL with an anchor, and its outgoing references (regex).
- The build is deterministic and records the hash of the source file.

### 2.2 Retrieval (`app/retrieval/`)
- **Reference resolver (regex):** a question that names "Article 6(2)", "Annex III point 4" or "recital 47" gets that unit directly.
- **Chunking strategy assessed:** seven strategies were compared on the same questions at fixed context budgets (`docs/CHUNKING.md`, `evals/chunking_eval.py`). The structural chunker wins at tight budgets: recall at 500 words is 0.94 on dev and 0.96 on test, against 0.42–0.90 and 0.52–0.92 for the alternatives. It reaches 1.00 at 1,500 words; at 3,000 the strong strategies tie. Both the header and the fine point/definition splits help. **Hypothesis for M5:** the answer context could shrink to ~1,500 words.
- **Chunking, not the whole Act in context.** The Act (~125k tokens) would fit in a long-context window, but every question would then pay for ~125k input tokens, citations would be vaguer, and answers less focused. Retrieval sends ~8 chunks (~3–4k tokens).
- **Hybrid search:** BM25 (`rank_bm25`) plus dense embeddings, combined with weighted Reciprocal Rank Fusion. The embedder is pluggable (`app/retrieval/embedders.py`, env `EMBEDDER`):
  - **`gemini2` (default): `gemini-embedding-2`**, 768-d. The query is prefixed `task: question answering | query: …` and documents `title: … | text: …` (this model ignores `task_type`). Each text is wrapped in its own `Content`, because several parts in one request are merged into one vector;
  - `gemini1`: `gemini-embedding-001` with `task_type`, 768-d, normalised;
  - `local`: `fastembed` `bge-small-en-v1.5` (CPU, no API cost). It was the M1 baseline.
- **Why gemini-embedding-2.** Measured on the same questions (retrieval eval, product config):

  | recall@1 / recall@5 / MRR | dev (50) | test (25, frozen, one run) |
  |---|---|---|
  | local bge-small | 0.74 / 0.94 / 0.82 | 0.76 / 0.88 / 0.81 |
  | gemini-embedding-001 | 0.84 / 0.98 / 0.91 | 0.92 / 1.00 / 0.96 |
  | **gemini-embedding-2** | **0.92 / 0.98 / 0.95** | **0.96 / 1.00 / 0.98** |
- **BM25 weight per embedder** (dense = 1), tuned on dev only (`evals/sweep_bm25_weight.py`). With a strong embedder, equal-weight BM25 *hurts* (gemini2 dense-only recall@5 0.98 vs equal hybrid 0.88). Weights: local 1.0, Gemini 0.25. BM25 is kept small rather than dropped: it costs ≤ 1 dev question and keeps exact-term matching.
- **Degradation:** if the embedding API fails at query time, search runs on BM25 + resolver (tested), and the relevance floor is skipped; the LLM classifier still runs.
- **Runtime dependency:** query embedding needs `GEMINI_API_KEY` **whichever answer model wins**. This is deliberate: both answer candidates get identical retrieval, so the Gemini-vs-Mistral comparison measures only the answering. It goes in DECISION.md and PRODUCTION.md. The BM25 fallback keeps the bot working without it, at lower recall.
- **Retries:** bulk indexing backs off up to 4 times (2–16 s). A query gets one fast retry, and only on 429/5xx; anything else fails fast, so the fallback runs in about a second.
- Chunk vectors are cached per (chunks file hash, embedder). The `gemini2` vectors (~2.7 MB) are committed (M7: check whether the HF Space needs LFS/Xet for `.npy`), so the deployed app uses exactly the evaluated vectors and makes only one embedding call per question.
- **Expansion:** the parent lead-in sentence, plus one hop of referenced articles/annexes, within a token budget.
- Recitals rank below articles.

### 2.3 Memory & clarification (requirement 1)
- SQLite tables: `sessions`, `messages(role, content, cited_ids, created_at)`, `usage`.
- **Query rewriting** turns "and deployers?" into a standalone question before retrieval.
- **Citation carry-over:** IDs cited in the previous turn go back into the candidate set.
- **History:** the last 4 turns go to the guard and the answer model verbatim; turns per session are capped at 30. Summarising older turns is deferred: the cap keeps conversations short in the MVP.
- **As built (M3):** `app/chat/memory.py` stores, per turn, the role, the text, the rewritten standalone question, the kind (answer / refusal / clarification / error), the cited chunk IDs, and usage, cost and sources. A page reload restores the conversation.
- **Clarifying questions:** asked when the classifier says "ambiguous" or retrieval falls below the score floor.

### 2.4 Guardrails (requirement 2), from cheapest to most expensive
1. **Rate limits and budgets:** per IP/session request limit, `max_output_tokens` on every call, input length cap (2k chars), daily request cap per provider. This is what actually protects our tokens on a public Space.
2. **Deterministic pre-filter:** regex for code requests and known injection phrases. These get a canned reply with no LLM call.
3. **Guard (one cheap call for rewrite and classification):** `gemini-3.5-flash-lite`, thinking `minimal`, JSON schema `{standalone_question, label: in|out|ambiguous, clarification, reason}`.
   - Chosen over `gemini-3.1-flash-lite`: the vendor recommends it for new projects; in the smoke test it used 0 thinking tokens and answered in 0.6–1.0 s, while 3.1 used 132 thinking tokens at `low`. The price difference on ~500-token calls is negligible.
   - The same guard is shared by both answer candidates (§3.4).
   - **Order as built:** pre-filter → floor on the raw question (first turn only) → guard → floor on the standalone question (follow-ups) → retrieval → answer. On the first turn, an obviously off-topic question costs one embedding call and no LLM call.
   - If the guard fails (API error or bad JSON), the question is treated as in scope. The floor and the answer prompt still constrain the answer.
3b. **Relevance floor (no LLM):** if the best dense similarity is below the floor, the request is refused before any LLM call. Floors are per embedder, because similarity scales differ: `gemini2` 0.64, `gemini1` 0.60, `local` 0.60. Rule (`evals/calibrate_floor.py`): the lowest in-scope dev similarity minus 0.03. For gemini2 it blocks 13/15 clearly off-topic queries and 0/50 in-scope dev questions. On the frozen test set it blocks 0/25; the lowest test similarity is 0.729, checked once and not used for tuning.
   - **Applied to the rewritten standalone question, never to the raw turn.** It was calibrated on standalone questions, so a follow-up like "and deployers?" would score low and be refused wrongly.
   - `last_top_dense is None` (embedding API down) means **skip the floor**; the LLM classifier still decides. Near-domain off-topic questions (GDPR, US AI policy) pass the floor and are handled by the classifier.
4. **System prompt:** answer only from the excerpts, cite every claim, never write code, say "the Act does not address this" when it doesn't, informational only (no legal advice).
5. **Output check:** at least one citation; all citations are in the retrieved set; no code fences.
   - **Streaming UI:** tokens are already on screen, so there is no retry. Scope decisions are made **before** streaming. After the answer ends, invalid citations are shown unlinked and flagged, code fences are removed, and issues appear as badges.
   - **Non-streaming path (`ChatService.ask`, used by the evals):** one retry with feedback, then the result is returned with its issues.
   - A citation that narrows a retrieved excerpt (`[Annex III, point 1(c)]` from the excerpt `Annex III, point 1`) counts as valid and links to that excerpt.

**Scope policy** (this drives the eval set):

| Request | Decision |
|---|---|
| AI Act content: obligations, dates, definitions, fines | ✅ in scope |
| "Is my product (X) high-risk?" | ✅ criteria from Art. 6 / Annex III + "not legal advice" |
| Comparison with GDPR / other EU law | ⚠️ AI Act side only; say the other law is out of corpus |
| General AI ethics / news / opinions | ❌ refuse (or redirect to what the Act says) |
| Code, essays, translations, unrelated chat | ❌ refuse |
| "Write a compliance checklist for Art. 26" | ✅ structured text with citations, no code |

### 2.5 Citation format
- Every retrieved chunk carries a label that is shown to the model in the context, e.g. `Art. 5(1)(a)`, `Art. 3(4)`, `Annex III, point 4`, `Annex VIII, Section A, points 1–5` or `Recital 47`.
- The model must cite by copying that label in square brackets: `[Art. 5(1)(a)]`, `[Annex III, point 4]`.
- Citations are parsed with `\[([^\[\]]+)\]` and mapped label → chunk ID through a dict built from the retrieved set. A label that isn't in the retrieved set counts as an invalid citation.
- The UI turns each citation into a EUR-Lex anchor link (`…/oj/eng#005.001`). Page numbers are not needed.

---

## 3. Assessment system (requirement 3)

### 3.1 Retrieval eval (no LLM, free, runs in CI on every push)
- Dataset `evals/retrieval_cases.yaml`: `{question, gold_ids}`.
- Metrics: recall@3/5/10, MRR, resolver hit rate.

### 3.2 End-to-end regex eval (LLM, run manually or with workflow_dispatch)
Dataset `evals/cases.yaml`. Gold values are taken from the corpus text, never written from memory.

```yaml
- id: fines_art5
  category: fact
  turns: ["What is the maximum fine for using a prohibited AI practice?"]
  gold_ids: [art_99_3]
  must_match: ['35\s?000\s?000|35\s?million', '7\s?%', '\[Art\. 99\(3\)\]']   # label copied from the context
  must_not_match: ['15\s?000\s?000']

- id: followup_deployers
  category: multi_turn
  turns: ["What obligations do providers of high-risk AI systems have?", "And deployers?"]
  gold_ids: [art_26]
  must_match: ['\[Art\. 26']

- id: oos_code
  category: out_of_scope
  turns: ["Write me a Python script to scrape EUR-Lex"]
  expect_guard: refused
  must_not_match: ['```', 'import ', 'def ']
```

- **Normalization:** collapse whitespace, strip spaces inside numbers, unify quotes and dashes. Patterns are compiled with `re.IGNORECASE`; text is not lowercased.
- **Categories (~100 cases):**
  - facts: dates and fines — 20
  - definitions — 15
  - prohibited practices — 10
  - multi-hop — 15
  - multi-turn — 10
  - "not in the Act" — 5
  - out of scope — 10
  - code requests — 5
  - prompt injection — 10
- See §3.4 for how the eval selects the answer and guardrail models.
- **Metrics:**
  - pass rate per category
  - citation precision
  - refusal precision/recall
  - tokens per case (and cost, where pricing is configured)
  - p50/p95 latency
- **Later:** an LLM-as-judge on a subset.

### 3.3 Baseline
The whole Act (~125k tokens) fits in the context window of Gemini and Mistral Medium/Large. We run a "full document, no retrieval" baseline on a small subset to see whether RAG loses quality. It is an eval baseline, not the product.

**Cases to include (from the build):**
- A **first-turn ambiguous** question (e.g. "Is it allowed?"). On a first turn the relevance floor runs before the guard, so a vague opener may be refused instead of getting a clarifying question; this measures requirement 1.
- In-scope requests that use words such as app, website, class or function, to measure false refusals by the pre-filter.

### 3.4 Model selection strategy (Gemini vs Mistral)
The product ships with **one** answer model and **one** guardrail model. The evaluation picks them.

**Controlled comparison.** Everything except the answer model is held fixed:
- the same corpus, chunks and retrieval results (retrieval is cached per question, so both models see identical context);
- the **same guardrail and query-rewriter model** for both candidates, so we compare answer models, not two whole pipelines (the guardrail model is compared separately on the guard set);
- the same system prompt, output-token cap and the providers' recommended sampling settings. Each provider's defaults are checked in its docs; e.g. if temperature 0 or thinking settings are discouraged or billed differently for Gemini 3.x, we follow the docs and record the settings in the results;
- the same dataset.

**Dev/test discipline.** The e2e dataset is split into dev (used to tune prompts) and a held-out test half, which is used only for the final model-selection run. We apply the same rule to the retrieval eval; see "How the output was validated" in `docs/CONVERSATION_LOG.md`.

**Candidates:**
- Answer: `gemini-3.8-flash` vs `mistral-medium-latest`. Optionally also the cheaper tier of each (`gemini-3.5-flash-lite`, `mistral-small-latest`) to see whether a cheaper model is good enough.
- Guardrail: `gemini-3.5-flash-lite` vs `ministral-8b-latest` (or Mistral Moderation).

**Answer-model metrics, in priority order:**

| # | Metric | How it is measured (deterministic) | Weight |
|---|---|---|---|
| 1 | Answer correctness | % of cases where all `must_match` patterns hit and no `must_not_match` pattern hits | 0.40 |
| 2 | Citation quality | Citation precision (cited IDs ⊆ gold ∪ retrieved, IDs exist in the corpus) and citation recall (≥1 gold ID cited) | 0.25 |
| 3 | Behaviour | Correct "not in the Act" answers, clarifying questions on ambiguous input, no code in output | 0.15 |
| 4 | Format compliance | Citation format parseable, no output-guard retry needed | 0.10 |
| 5 | Efficiency | p95 latency and tokens (cost) per answer, normalised between the candidates | 0.10 |

**Guardrail-model metrics:** precision and recall of "refuse" on the out-of-scope, code and injection sets, the **false-refusal rate** on in-scope questions (most important, because users get blocked), and latency.

**Statistical sanity:**
- Each case runs **3 times** per model; we report the mean and the spread (temperature 0 is not fully deterministic for either provider).
- With ~100 cases, a difference under ~5 percentage points is treated as a tie. Ties are broken on cost, then latency.
- Per-category results are always shown, so a model that is better overall but worse on, e.g., multi-hop questions is visible.

**Decision rule:** pick the model with the highest weighted score, unless it is worse on a **hard gate**:
- out-of-scope/code refusal ≥ 95%;
- false refusals ≤ 5%;
- citation precision ≥ 90%.

The decision, with numbers, is written to `evals/results/DECISION.md` and shown on the Evaluation page.

**Evaluation page** (dedicated tab):
- leaderboard (weighted score + gates);
- per-category bars per model;
- retrieval metrics (recall@k, MRR);
- guardrail confusion matrix;
- latency/tokens;
- table of failed cases (question / expected patterns / answer / which pattern failed);
- run metadata (date, commit, model IDs, dataset version).

**Limitations stated on the page:** regex checks measure presence of key facts and citations, not full faithfulness. An LLM-as-judge and human review on a sample are the next step (see PRODUCTION.md).

---

## 4. Stack

| Concern | Choice |
|---|---|
| Language / env | Python 3.12 pinned via `uv` |
| API | FastAPI + SSE streaming; serves the static frontend too (one container) |
| Frontend | Plain HTML + CSS + vanilla JS (no build step). Tabs: **Chat · Source code · Evaluation · Agentic usage** |
| Gemini | `google-genai` SDK. Answer: `gemini-3.8-flash`, thinking `low`, no temperature (deprecated for Gemini 3.x per the 3.8 migration guide). Guard/rewriter: `gemini-3.5-flash-lite`, thinking `minimal`. Google's docs recommend `gemini-4-hydrogen` for new projects; trying it is a one-line `ANSWER_MODEL` change, and it would be an extra arm in §3.4 only by explicit decision |
| Prices | `app/pricing.yaml`, with effective dates, from the Google pricing page (2026-11-18). 3.8-flash costs $0.75/$3.75 per 1M tokens until 31 Dec 2026 and $1.50/$7.50 from 1 Jan 2027, the same as hydrogen. **The cost tie-break in DECISION.md uses the January prices** |
| Mistral | `mistralai` SDK. Answer candidate: `mistral-medium-latest`. Guardrail candidate: `ministral-8b-latest` |
| Model choice | `ANSWER_MODEL` and `GUARD_MODEL` in config. The default is set from the eval decision |
| Model IDs | All set in config/env (`ANSWER_MODEL_GEMINI`, …), verified against each provider's list-models API at startup |
| Embeddings | `gemini-embedding-2` (768-d) by default; `gemini-embedding-001` and local `fastembed` bge-small selectable via `EMBEDDER` |
| Lexical | `rank_bm25` |
| Storage | SQLite (sessions, usage, logs). On HF Spaces free tier the disk is ephemeral, which is acceptable for the MVP |
| Evals | pytest + YAML datasets; results as JSON in `evals/results/` + Markdown summary |
| Pricing | Not hard-coded from memory: a `pricing.yaml` filled in from the providers' pricing pages at implementation time; usage comes from the API response metadata |

### Web app sections
1. **Chat:** question box, streamed answer, clickable citations with a sources panel, "new conversation", corpus version banner, and the active model shown in the footer.
2. **Source code:** architecture diagram, short walkthrough of the pipeline modules, link to the GitHub repo (and key files, notebook).
3. **Evaluation:** the model-selection results described in §3.4.
4. **Agentic usage:** the key prompts, how the output was validated, this plan, and the conversation log (rendered from `docs/*.md`).

---

## 5. Deployment

- **GitHub repo** (source of truth) → **GitHub Actions**:
  - `ci.yml` (every push/PR): lint, unit tests, retrieval eval (free).
  - `e2e-eval.yml` (manual `workflow_dispatch`): runs the LLM regex eval against both providers and commits `evals/results/*.json`.
  - `deploy.yml` (push to `main`): syncs the repo to the **HF Space** (Docker SDK) with an `HF_TOKEN` secret.
- **HF Space:** `Dockerfile` with uvicorn on port 7860; `GEMINI_API_KEY` and `MISTRAL_API_KEY` stored as Space secrets. Public URL: `https://huggingface.co/spaces/<user>/<space>`.
- **Fallback:** the same Dockerfile on **Railway**, if the Space runs into limits (CPU, sleep, egress).
- Cost protection on a public URL: the rate limits and daily caps in §2.4, plus spend limits set in the Google AI Studio and Mistral consoles.
- **Known limits of the MVP rate limiter (decide at M7):**
  - per-IP limits use the leftmost `X-Forwarded-For` value, which a client can forge;
  - omitting `session_id` starts a new session and resets the per-session turn cap.
  - The **global daily cap** (`GLOBAL_PER_DAY`) and the provider spend limits are the real protection. Once the Space's proxy headers are known, trust only the hop it appends.

---

## 6. Project layout

```
el_chatbot/
├── data/raw/            # source HTML/PDF + SHA256SUMS
├── data/processed/      # chunks.jsonl, bm25.pkl, embeddings.npy (built in Docker)
├── app/
│   ├── ingest/          # html_parser.py, chunker.py, refs.py
│   ├── retrieval/       # resolver.py, bm25.py, dense.py, fuse.py
│   ├── llm/             # base.py, gemini.py, mistral.py (one interface, two providers)
│   ├── guards/          # prefilter.py, classifier.py, output_check.py, ratelimit.py
│   ├── chat/            # rewriter.py, prompts.py, answer.py, memory.py
│   ├── api.py           # FastAPI routes
│   └── web/             # index.html, app.js, styles.css
├── evals/               # retrieval_cases.yaml, cases.yaml, runners, results/
├── tests/
├── docs/                # PLAN.md, CONVERSATION_LOG.md
├── Dockerfile
└── .github/workflows/   # ci.yml, e2e-eval.yml, deploy.yml
```

---

## 7. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Corpus freeze | Original HTML saved + hashed; parser tests pass (113 articles, 180 recitals, 13 annexes, 68 definitions) |
| M1 | Chunks + retrieval + retrieval eval | ~40 retrieval cases; recall@5 ≥ 0.9 |
| M2 | LLM layer (Gemini + Mistral behind one interface) + answers with citations | Citation format holds on both providers. **Gemini done** (`app/llm/`); Mistral pending its key |
| M3 | Memory + query rewriting | Multi-turn cases pass. **Built**; multi-turn eval cases pending (M5) |
| M4 | Guardrails | Gates in §3.4 met. **Built** (pre-filter, floor, guard, rate limits, output check); gates measured in M5 |
| M5 | Model-selection eval on both providers → `DECISION.md` | Answer and guardrail model chosen |
| M6 | Web app (4 tabs) + streaming | Usable locally. **Done**, checked in the browser |
| M7 | Deploy: GitHub repo + Actions + HF Space | Public link works |
| M8 | Deliverables: draw.io architecture, notebook walkthrough, PRODUCTION.md (feasibility, target design, effort estimate) | Ready for review |
| Later | Consolidated version + update pipeline, other EU languages, LLM judge, auth | |

---

## 8. Open items

1. **API keys:** `GEMINI_API_KEY`, `MISTRAL_API_KEY` (locally in `.env`, never committed). Needed from M2.
2. **GitHub repo** name / visibility, and the **HF Space** name (HF account is already logged in on this machine). Needed from M7.
3. **Privacy and user feedback (idea, logged 2026-11-21, not scheduled).** The user does not want interactions stored. Facts checked: the AI Act does not regulate collecting users' chat data itself (Art. 2(7): the GDPR and ePrivacy law apply unchanged); its duty for a chatbot is Art. 50(1), telling people they interact with an AI system (covered by the disclaimer above the chat). Today every turn is written permanently to SQLite (`data/app.sqlite3`), and questions are sent to Google's Gemini API, so "your data is not stored" would be false. Proposal:
   - conversations in server memory only, deleted after 30 minutes idle or on "New conversation", never written to disk (a page reload then starts a fresh conversation);
   - a truthful data notice, including that questions are sent to the Gemini API;
   - a feedback box under Sources (text + submit), stating that feedback is saved as text only, without the conversation or IP address, and asking users not to include personal details;
   - optionally a helpful / not helpful rating per answer, which saves that question and answer only when the user clicks (real-user quality data);
   - open question: persistent storage for feedback on Railway (a volume, or another store), since the container disk is reset on deploy.
