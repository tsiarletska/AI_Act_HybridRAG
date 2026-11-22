# Agentic usage: full conversation log (archive)

This is the complete, turn-by-turn record (from Turn 1, 2026-11-17): user messages verbatim, agent actions summarised. It is kept as evidence. The condensed version shown in the app is `docs/CONVERSATION_LOG.md`.

---

## Key prompt

> Our objective would be to build a MVP of the NL interface, which would allow use to chat with the LLM on the specific documents (basically RAG chatbot).
> The document which we would need to work on: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689 comes in PDF and in the HTML formats.
> so far we can focus on English only, and if we would have a time later we can discuss other langauges as well.
> 1) chatbot should keep a memory and allow user to give more of the clarification questions
> 2) we should have the guardrails (we do not wanna users spend our tokens on writing unrelated code or chat with the LLM on the unrelated topic).
> 3) we should have an assessment system. i propose to have a deterministic layer, some dataset which may help us to evaluate the code using simple regex.
> analyse the document, and lets work on the plan of the web application

---

## Log

### Turn 1 — 2026-11-17 · Analyse the document, draft the plan

**User:** the key prompt above.

**Agent actions:**
- Downloaded the EUR-Lex HTML and PDF of CELEX 32024R1689 (144 pages) and parsed the HTML structure with BeautifulSoup.
- Found stable anchors: `rct_N` (180 recitals), `art_N` (113 articles), `NNN.PPP` (509 article paragraphs; verified `005.001` = Art. 5(1)), `anx_X` (13 annexes), `cpt_X` (13 chapters). Total size is ~90k words ≈ 125k tokens; Art. 3 has 68 definitions.
- Extracted gold facts from the text for future evals: the fines in Art. 99(3)–(5) (EUR 35 000 000 / 7 %, 15 000 000 / 3 %, 7 500 000 / 1 %) and the application dates in Art. 113.
- Noted text gotchas for the regex evals: spaced numbers (`35 000 000`, `7 %`) and flattened superscripts (`10 25`).
- Wrote `docs/PLAN.md` and saved the source files with SHA-256 hashes in `data/raw/`.

**Agent reply (summary):**
- Proposed chunking by the document's own structure, hybrid retrieval (regex reference resolver + BM25 + embeddings), and memory through query rewriting plus carrying over cited articles.
- Proposed layered guardrails, from cheapest to most expensive: rate limits, regex pre-filter, cheap scope classifier, grounded system prompt, output check.
- Proposed a two-layer deterministic eval. Retrieval recall@k needs no LLM. The end-to-end regex eval works because a fixed citation format such as `[Art. 99(3)]` is enforced.
- Flagged that the corpus version should be checked before freezing it.
- Asked four questions: LLM provider, frontend, deployment, citation granularity.

### Turn 2 — 2026-11-18 · Decisions

**User:**
> right, answer to your questions:
> 1) Gemini models and Mistral
> 2) HTML. structure: the interface itself, where user can ask the question, 2) the source code (engine on python) 3) evaluation results 4) agentic usage (here we would need to provide the key prompt and the plan that we would develop i order to completed the task). in oreder to provide the key prompt, create the .md file and log our convesration there.
> 3) would be nice to try Hugging Space, otherwise the GitHUb Action or Railway. would need to provide the link to the system
> 4) citations: i'd go with the links to the article and paragraphs only. not a strict requirement on it

**Agent actions:**
- Looked up current model IDs on the providers' model pages:
  - Gemini: `gemini-3.8-flash`, `gemini-3.5-flash-lite`.
  - Mistral: Small 4, Medium 3.5, Large 4, Moderation 2.
  - IDs stay configurable and are checked against the list-models APIs at startup.
- Checked the corpus version and found a **consolidated version of the AI Act dated 27.07.2026** (`02024R1689-20260727`). It includes the "Digital Omnibus on AI" amendments, which postpone the high-risk deadlines. The original text would give outdated dates.
- EUR-Lex now returns a bot challenge to scripted downloads, so the consolidated HTML has to be saved from a browser.
- Updated `docs/PLAN.md`:
  - Gemini + Mistral behind one LLM interface, and the eval runs on both providers.
  - Plain HTML/JS app with four tabs.
  - Deployment: GitHub repo → GitHub Actions → HF Space (Docker), with Railway as fallback.
  - EUR-Lex anchor links for citations.
  - Local `fastembed` embeddings so the image stays small.
- Created this log.

**Open items for the user:** corpus version (consolidated recommended) and a browser download of it, API keys, GitHub repo and HF Space names.

### Turn 3 — 2026-11-18 · Assignment frame, single answer model, original corpus

**User:**
> 1) we are not going to use mistral and gemini as answering models at the same time. we would do teh test of the evaluation - which one is showing better results. we would need to develope also the evauation startegy. and the result would be located on the dedicated for it page
> 2) i agree, we need a cheap model as a guidrail.
> 3) source: lets go with te original one.
> we are doing the task in te frames of the following instruction:
>
> *Your task is to create a natural language interface prototype that allows users to ask questions about a specific EU regulation (i.e., AI Act) from Eur-Lex. The goal of this AI solution is to provide a user-friendly system that can understand and respond to queries related to the content of the selected regulation. The sketch should be done to the level that will enable you to answer questions related to feasibility of building production system, design of the target solution and effort estimation.*
> *Knowledge base: To limit the scope of the required data processing and preparation you can focus on a single regulation (i.e. AI act): https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng.*
> *Outputs: • Solution architecture: (e.g. draw.io diagram) describing system components with inputs and outputs • Prototype code: please note that all code should be written in Python and prepared as an ipython notebook (.ipynb) and/or Python files (.py). You are welcome to use AI coding assistants. If you do, please share the key prompts used and briefly describe how you validated the output.*

**Agent actions:**
- Mapped the assignment's required outputs to files in the repo:
  - draw.io architecture diagram;
  - `.py` package + walkthrough notebook;
  - key prompts and validation notes (this file);
  - `docs/PRODUCTION.md` for feasibility, target design and effort estimate.
- Changed the plan to one answer model, chosen by evaluation. Added §3.4 "Model selection strategy":
  - a controlled comparison with identical retrieval and prompts, run 3 times per case;
  - weighted metrics: correctness 0.40, citations 0.25, behaviour 0.15, format 0.10, efficiency 0.10;
  - hard gates on refusals and citation precision;
  - a tie threshold, and a decision recorded in `evals/results/DECISION.md`.
- Added a separate guardrail-model comparison: refusal precision/recall and false-refusal rate.
- Switched the corpus to the original OJ text. A UI banner warns that later amendments (Digital Omnibus 2026) are not reflected.

### Turn 4 — 2026-11-18 · Build M0–M1: parser, chunks, retrieval, retrieval eval

**User:** (continued from Turn 3: "lets go with the original one")

**Agent actions:**
- Set up a `uv` project with Python 3.12.
- Wrote the HTML parser (`app/ingest/html_parser.py`) and the structural chunker (`app/ingest/chunker.py`). They produce 893 chunks: 180 recitals, 68 definitions, article paragraphs and points, and annex points. Each chunk has a canonical ID, citation label, EUR-Lex anchor URL and outgoing references.
- Wrote the retrieval layer:
  - a deterministic reference resolver (`app/retrieval/resolver.py`), which separates *exact* references (named paragraph or point) from *scope* references (an article mentioned in passing);
  - BM25 with a small lay→legal glossary;
  - local dense embeddings (`fastembed`, bge-small);
  - Reciprocal Rank Fusion to combine them.
- Wrote the retrieval eval (`evals/run_retrieval_eval.py`): a dev set of 50 questions, a held-out test set of 25, and an ablation over the components.
- Calibrated the off-topic relevance floor (`evals/calibrate_floor.py`).
- An agent-side review flagged mistakes, which were fixed:
  - Duplicate chunk IDs were being renamed silently. They now raise an error, which immediately exposed a real parser bug: Articles 102–110 quote paragraphs of *other* regulations, and those carry foreign anchor IDs.
  - A resolver regex had been tweaked after held-out test failures were visible. The tweak was reverted and the test set is now frozen.
  - The plan's citation format didn't match the real chunk labels. The plan now uses the labels.

### Turn 5 — 2026-11-18 · Gemini key, chunking confirmed, Gemini embeddings

**User:**
> i've addded the gemini first, mistral gonna come up bit later on.
> i suppose that even tho the document is small we shoudl still use chunking rather then fit it into the same context window.
> so for the embeddings I think we may use one of the gemini models as well for this process.

**Agent actions:**
- Listed the models available to the key through the API. Embedding models: `gemini-embedding-001` and `gemini-embedding-2`.
- Smoke-tested both and checked the installed SDK and the docs. Found two pitfalls:
  - `gemini-embedding-2` merges several texts in one request into a single vector;
  - it ignores `task_type`, so text prefixes are used instead.
- Made the embedder pluggable (`app/retrieval/embedders.py`): `local` / `gemini1` / `gemini2`, each with its own vector cache and relevance floor.
- Compared all three on the same retrieval eval.
  - gemini-embedding-2 is best: recall@5 dev 0.98 / test 1.00, against 0.94 / 0.88 for the local model.
  - With a strong embedder, equal-weight BM25 fusion hurt results, so the BM25 weight was tuned on dev (0.25 for Gemini).
- Added a fallback: if the embedding API fails, search uses BM25 + resolver. A test covers it.
- An agent-side review flagged three issues, which were fixed:
  - the query path retried for up to ~30 s before falling back; it now fails fast, with retry tests;
  - the floor needed a check on unseen data; it blocks 0/25 test questions;
  - the floor must run after the query rewrite, and be skipped when dense retrieval is unavailable. This is recorded in PLAN 3b.
- Chunking kept, as agreed. Reasons are recorded in PLAN §2.2: cost per question, precise citations, focused answers.

### Turn 6 — 2026-11-18 · Assess chunking strategies

**User:**
> questions is: lets assess various chunking stategies, what would be the best approach considering the nature of teh document

**Agent actions:**
- Analysed the document's properties that matter for chunking: legal hierarchy with anchors, ~250× variation in unit size, lead-in-dependent points, context in headings, 68 definitions in one article, recitals vs articles, annex lists, and cross-references.
- An agent-side review shaped the method before any code was written:
  - strategy-agnostic gold, counted by 5-gram coverage of each unit's own text with the repeated lead-in removed;
  - recall at a fixed word budget instead of recall@k, which would favour big chunks;
  - the same source text for every strategy;
  - dense-only as the primary view, because of the structural chunks' home advantage;
  - the resolver excluded from the comparison.
- Fixed an embedding-title bug the review found: an empty header did not fall back to `none`.
- Wrote `evals/chunking_eval.py`, comparing seven strategies: fixed 250/500, recursive 350, article, paragraph, structural, and structural without header.
- Offline checks before any API call: every unit's own text appears in the source text (0 misses); lead-in stripping verified; the citability ceiling was traced to mirrored provisions (Art. 22 ≈ Art. 54).
- Results:
  - Structural wins at tight budgets (500/1,500 words) on dev and test, and reaches full recall with half the context. At 3,000 words the strong strategies tie.
  - Paragraph-level is the closest competitor; on dev it misses only on oversized units (Art. 3, Art. 5(1)).
  - The header and fine granularity both help, but their relative size varies between dev and test (header: +18 on dev, +4 on test at D@500).
- A second review caught overstatements in the first write-up, which were corrected:
  - "best at every budget" (false at 3,000 words);
  - a dev-only header figure presented as general;
  - a citability tie-break that is a metric artifact.
- Decision: keep the production chunker. Shrinking the answer context to ~1,500 words is a hypothesis for the end-to-end eval. Write-up in `docs/CHUNKING.md`.

### Turn 7 — 2026-11-18 · Log the chunking evaluation; build the interface

**User:**
> log the evaluation whcih have been done on the chunking strategy.
> lets start to build the interface

**Agent actions:**
- **Evaluation log:** created `docs/EVALUATION_LOG.md`, one entry per evaluation (E1–E6) with method, command, results, decision and caveats. The chunking assessment is E5; full write-up in `docs/CHUNKING.md`. The Evaluation tab renders this log.
- **Models checked before coding:**
  - read the model list, model pages, pricing page and the Gemini 3.8 migration guide;
  - temperature is deprecated for Gemini 3.x; `thinking_level` replaces it, and 3.8-flash rejects `minimal`;
  - Google recommends `gemini-4-hydrogen` for new projects; 3.8-flash stays the answer candidate (stable, half the price until 31 Dec 2026), and prices are stored with effective dates.
- **Smoke tests** of streaming, the output cap, and JSON-schema output on both Flash-Lite models. Chose `gemini-3.5-flash-lite` with `minimal` thinking as the guard.
- **Built the backend:**
  - provider interface (`app/llm/`);
  - one `ChatService` used by both the UI (streaming) and the evals (non-streaming), so the evals run the exact code the user sees;
  - guard call that rewrites and classifies in one go;
  - pre-filter, relevance floor, rate limits;
  - citation validation with label normalisation;
  - SQLite memory;
  - FastAPI with SSE.
- **Built the frontend:** plain HTML/CSS/JS with four tabs (Chat, Source code, Evaluation, Agentic usage).
- **Security choices for a public URL:**
  - model text is always HTML-escaped, and citation links are built from server data;
  - the source viewer serves a fixed allow-list, never a client path;
  - rate limits and a daily cap.
- An agent-side review shaped the build order (vertical slice, one pipeline function, smoke tests first) and flagged a design conflict: you can't "retry then fall back" once tokens are streamed. It is resolved in PLAN §2.4.5.
- **Tests:** 79 unit tests, including pipeline tests with a fake LLM, which check:
  - no LLM call for pre-filter and floor refusals;
  - the follow-up rewrite and citation carry-over;
  - code-fence removal and the retry path.
- **Browser check:** all four tabs, an in-scope question, a follow-up, and an off-topic question. It found and fixed:
  - a missing Art. 113 for date questions;
  - narrowed citations wrongly flagged as invalid;
  - a message dropped while an answer was streaming;
  - Markdown lists not rendering.
  See E6 in the evaluation log.
- A final agent-side review found three more problems, which were fixed with tests:
  - shared search state between concurrent users;
  - pre-filter false refusals for in-scope wording;
  - the date rule firing on conditional "when".
  It also flagged the forgeable `X-Forwarded-For` rate-limit key for the deployment step.

### Turn 8 — 2026-11-19 · Architecture scheme; guard overhead in the evaluation

**User:**
> So what I was thinking about first, let's draw the scheme overall, how the system would look like. So we have discussed that we're gonna use some cheap model to serve as guardrail and to understand the relevance of the user's questions to the topic in order to save some tokens for more strong model which gonna respond. And I want to also have it as a part of the evaluation process to check how much latency does it add to the system and how much overall cost. So let's start with the scheme, prepare it as an artifact, and then I want to work with design in general and open this HTML page on my browser to check it out. And yes, if there is any questions to me that we need to resolve now, please prepare the list and output it. I will work for them.

**Agent actions:**
- Drew the architecture as an HTML page (`docs/architecture.html`, also published as an artifact):
  - the request path, colour-coded by what each step costs (no API call / embedding / cheap LLM / main LLM), with early exits and indicative latency and cost per step;
  - a cost table per question type;
  - a break-even estimate for the guard: ~11% off-topic share today, ~6% after the January price change;
  - the offline build and the evaluation loop;
  - the planned overhead experiment;
  - the deployment.
- Added experiment **E7, overhead of the gate**, to the evaluation plan: configurations A (full gate), B (no guard) and C (no floor), measuring latency p50/p95, cost per 100 questions at two traffic mixes, refusal accuracy and false refusals.
- Listed the open questions for the user.

### Turn 9 — 2026-11-19 · Methodology

**User:**
> write the metholdofgy file and document there all the process.

**Agent actions:**
- Wrote `docs/METHODOLOGY.md`, which ties the whole process together: principles, problem framing, corpus analysis, chunking, retrieval, generation and memory, guardrails, the assessment system (experiments run and planned), engineering and tests, how the AI agent was used and its output validated, a timeline, limitations and how to reproduce the results.
- Added it to the "Agentic usage" tab of the web app.

### Turn 10 — 2026-11-19 · The guard's role; multilingual design

**User** (four messages):
> okay so in the scheme you have prepared - the 3rd guard - what would be objetcive of it?

> you think it might be over engineering

> okay, so that is useful for the memory?

> So there are a lot of languages this document have, like a different variation and translation, and it's kind of cool because there is like all the terminology is correct and revised. So I wanted to play about this idea a bit more, and if we to keep the third layer of LLM, which can identify the intent of the user, we can also use it for the language identification in order for the response would be in correct language. However, if we do so, how are we gonna deal with embeddings and the vector database? Do we need to create different indexes, so to say? Because I mean, we don't want to mix them up all, right? Because it would create some mess. But there are also like 15 to 20 languages, and do we need to use 20 indexes for all of those papers? So I would like to have such feature, because I think it's nice and it's quite unique for the system like this, but I'm not sure how to organize it with a vector database and whether we need it in general, because the documents itself are quite small.

> Okay, so I think we don't maybe need to keep all 24 languages, and we can maybe stop on 5 of them. But the idea for this infrastructure should be scalable [...] So then we're gonna keep like English version, we can keep Lithuanian, Polish, Let's also keep Finnish and Italian [...] Or maybe instead of Italian, let's keep French. [...] English index plus align text. Yeah, actually. I think that's something that I originally have had in mind. Do you think then the search itself and retrieval would be a bit better, because like English is the native language of many models in general [...] I want to elaborate a bit more on the test also.

**Agent replies (summary):**
- **The guard's three jobs:** rewrite follow-ups into standalone questions (needed for search to use memory), scope classification (catches near-domain off-topic and reworded code requests that the free checks miss), clarification questions.
- **Over-engineering?** Partly. The money saved per stopped question is small and the rate limits are the real spend protection, while every valid question pays ~1 s. The rewrite and clarification jobs are essential. Proposed a conditional guard (follow-ups and borderline first turns only) as a fourth E7 configuration, measured before changing anything.
- **Multilingual design:** the Act exists in 24 equally authentic, structurally aligned language versions. Compared one index per language, one mixed tagged index, and **one English index plus aligned texts** (search in English via the guard's rewrite, then swap in the official text of the same chunk IDs in the user's language). The user leans to the last one, with 5 languages: English, Lithuanian, Polish, Finnish, French.
- Discussed whether English-pivot search is better, and how to test the multilingual feature.

### Turn 11 — 2026-11-19 · Plain-language vs formal answers

**User:**
> okay, good so the concept have been st.
> also in the inetrface i wanna add a toggle -to allow user to have formla or informal answer. cause you know it is a law it is heavy to read an dif user wanna have a simple answer to the simple quetsioni would like to rpovide it.
>
> so in the third layer we can identify with LLM: user intend, langauge and the tone to contruct the final prompt to the generation model. but we would alo need to test its effectiveness, is not it right?

**Agent reply (summary):**
- A toggle is an explicit user choice, so the style should come from the toggle, not be inferred by the guard. The guard keeps intent and language; fewer guesses means less to go wrong and less to test.
- The grounding rules (excerpts only, citations, no code) stay identical in both styles; only a style block in the answer prompt changes.
- Proposed a test plan: paired runs of the same questions in both styles, checking that facts and citations do not drop, that plain answers are measurably easier to read (deterministic readability measures), that conditions and exceptions survive simplification, and that the toggle works mid-conversation and in every language.

### Turn 12 — 2026-11-19 · Multilingual retrieval experiment (E8)

**User:**
> This is still a hypothesis, so I'd make it the first multilingual experiment.

(Quoting the agent's previous reply; taken as the go-ahead to run the experiment.)

**Agent actions:**
- Ran the two arms that need no other language texts: translate-to-English-then-search and direct search of the untranslated question, with an English rewrite control. The native-index arm is deferred until the language versions are saved from a browser.
- Translated the 50 dev questions into Lithuanian, Polish, Finnish and French with a stronger model than the rewriter, and froze them in `evals/retrieval_cases_ml.yaml`. The production guard prompt was not changed; the multilingual rewrite prompt is local to the experiment.
- Results: translate-first matches English at recall@5 and stays within 4 pp on MRR. Direct search is weaker at top-1, misses article references and would wrongly refuse 2/200 questions at the first-turn floor. Language detection was 250/250 correct, with no false refusals. Details in E8 of the evaluation log.
- Fixed two bugs the run exposed, each with tests: the resolver did not understand "point 8 of Annex III" (English users too), and concurrent first calls could close the shared Gemini client mid-request.

### Turn 13 — 2026-11-19 · Multilingual flow in the architecture scheme

**User:**
> add the scheme of the multilinual rag in here below so i cna assess the flow

(with the link to the architecture artifact)

**Agent actions:**
- Added section 6 to the architecture page (`docs/architecture.html`):
  - the online flow for a non-English question: pre-filter, language check, guard (language, scope, English rewrite with the official term glossary), floor on the English rewrite, retrieval on the one English index, swap to the official text by chunk ID, answer in the user's language with the style toggle, extended post-check, localised display;
  - each step marked as built, tested in E8, or to build;
  - the offline build per language: same parser, alignment checks, English-only embeddings, aligned text store and term glossary;
  - the E8 results and what remains to test.
- Checked the rendering in the browser and fixed three overlapping labels.

### Turn 14 — 2026-11-19 · Guard simplification; end-to-end test design

**User:**
> Okay, so basically we can have like two couple functions for the quote and injection patterns. Then we have also the language check, which we can also solve with some no LLM solutions. And then we will have only LLM for the for what the language is still written in the scheme. Do we need to validate the language on the step to match it with the result, or what? Why do we have it? Scope and in English rewrite, what's gonna be there? Okay, so I see that the links should be in the user's language. It's okay. Then I want to elaborate a bit more on the test design and how the dataset would look like. So finally I want to perform three tests. So by the matrix I want to have some deterministic test of the answer. So just to cover it all, it would be the same data set, and I think it would contain like the data on, let's say, 1,000 interactions. And since we have like 5 languages, we can do 250 per the language. So it would be equal number of them, I guess. And then we can do the deterministic, like the code one. I don't know, to check whether if the user asks about a certain terminology, whether the LLM would include this terminology at all in the response, or if the user asks about some term which is appearing like once in the document. For example, I saw the CCTV appearing twice in the document. So if the user asks about the, oh, can I scrap the, I don't know, can I put the CCTV like without the permission and develop my computer vision model by the scrap in the faces of other people appearing on the street, we would have two spots which model should return, because basically it's mentioned only twice in the documents. So yeah, we would need to check whether, I don't know, they'll correspond into, I think, just like, you know, mingling about the idea about the deterministic check. And then I want to have the LLM check on the same 1,000 samples, like using the stronger model. I'm not sure yet whether it's going to be Gemini or Claude. I will check my budget from the Claude. And then for English part I want to have a human check, which I'm gonna do, so it would be under my rules. I would score it myself. So LLM check would also in the scale from 1 to 10. I'm not sure, would it be reasonable to have LLMs reasoning why the response was bad or not, because it's kind of a lot of information already. And then so basically what I want to have regarding the test content, so the I want to have the samples where we're gonna have some injection test, how is the system gonna reject it in general, like what's gonna be a response, like it should be some automatic response to the user which gonna, I don't know, block their request or something, I imagine. Then the same outcome I expect with the out of the topic guards. Yeah, some the same response like, oh, I don't know, or blah blah blah, no, something more formal. So I want to have this point in this test as well. Then I want to have generally quality responses from the LLM, and then we just check it against the document, like human-wise, I don't know, other model check it, whatever. So that would be quality kind of responses. And then I want to also measure the latency on the each step, how the pipeline is going, from how much time it's taking to go through the, let's say, pre-filters and language check, and then through the LLM, the first LLM which serving as a guard, then also the retrieval pipeline, how like, I don't know, let's say how fast the user would receive their rejection in case of a prompt injection, and how fast user would receive the rejection when they ask something out of the topic, and how fast user will receive the answer when the question is actually relevant. And I don't know, I also wrote down the case that we can test in the, I don't know, test scenarios is non-present language. I don't know, we can add a couple of the languages which are out of those 5, maybe a couple of questions, no more, because we are maybe 5 of them, you know, so it would be more like equal, but I'm not sure, validates this idea. So as an output, when we're gonna run this test, I want to have like the, I don't know, CSV file which I can analyze, like which model we have used on each step, through this pipeline, like basically generating question and answer. I don't know.

**Agent reply (summary):**
- Language detection moves to a deterministic detector, used twice: on the question (to choose the path) and on the answer (to check it is in the asked language). The guard keeps two jobs: scope label and the English rewrite.
- Proposed the end-to-end test design: 200 base scenarios written in English and translated into the other four languages (1,000 interactions, paired across languages), plus a small unsupported-language set; three evaluation layers on the same data (deterministic checks, an LLM judge with a per-criterion rubric and short reasons, human scoring of English with the same rubric); per-step latency by outcome path; one CSV row per interaction. Verified the user's CCTV example: the term appears in exactly two chunks, Art. 5(1)(e) and Recital 43.

### Turn 15 — 2026-11-19 · English only for the deadline; answer style toggle

**User:**
> okay so overall, lets stop in here developing this idea. now lets just focus on English:
> i relaly like the lnaguage idea, yet i might not have time to validate it all, since i have the deadline on sunday.
> so now lets stick to english and the tone. if i have more time on the weekend we do the multilanguage as well.

**Agent actions:**
- Built the answer style toggle: **Legal detail** (default) / **Plain language**.
  - `app/chat/prompts.py`: only rule 3 of the answer prompt is switchable (`STYLES`, `answer_system(style)`); "legal" reproduces the original prompt exactly.
  - `ChatService.stream/ask` take a `style`, validated before any call, and save it with each answer; `POST /api/chat` accepts `style` (`legal` | `plain`, anything else is rejected with 422).
  - UI: a two-option switch under the input box, remembered per browser; each answer's info line shows its style.
  - 6 new tests (prompt selection, shared grounding rules, default = original prompt, unknown style rejected before any call, style change mid-conversation).
- First plain-language answers were barely shorter (258 vs 263 words); the plain rule was tightened (about 150 words, at most four bullets, everyday words instead of legal phrasing). After that: 101–142 words on simple questions, with the same citations and exceptions; checked in the browser.
- Marked multilingual as post-MVP in the plan and methodology.

### Turn 16 — 2026-11-19 · Vector database question; 1,000-case dataset and the Gemini run (E9)

**User:**
> 1) do i need to crate an index on the pinecone?
> 2) yes i will do the mistral key today, but before i wanna have the results in form the gemini based solution as well as composed dataset with 1000 questions and answers which gonna be used for the assessment of the gemini models performance

**Agent actions:**
- **Pinecone:** not needed. The index is 893 vectors × 768 dimensions (~2.7 MB), held in memory and searched in about a millisecond; a hosted vector database adds a network hop, cost and a dependency with no gain at this size. It belongs in the production design for many documents, frequent updates or several app servers.
- **Dataset** (`evals/build_e2e_dataset.py` → `evals/e2e_cases.yaml`, frozen): 1,000 English cases, 700 dev / 300 test, generated by `gemini-4-hydrogen` (a stronger model than the answer model, same family: recorded as a caveat).
  - In-scope cases are generated from one chunk each (two for follow-ups), so the gold provision is known; every fact an answer must contain was verified to occur verbatim in its source chunk; questions sharing 5+ consecutive words with their chunk were dropped; coverage stratified across articles and annexes; near-duplicates removed.
  - Categories: provision 393, definition 61, scenario 54, rare term 60 (terms in at most two chunks, e.g. CCTV), multi-turn 60, not in the Act 30, ambiguous 40, off-topic 122, code 60, injection 120.
  - Read a stratified sample of 30 cases; fixed three injection patterns that would have matched the app's own refusal text. Generation cost $5.36.
- **Runner** (`evals/run_e2e.py`): the UI's streaming path, deterministic pass rules fixed before the first run, API errors kept apart from model failures, one CSV row per case (62 columns: question, answer, gold text, every check, models, tokens, cost, per-step timings, empty judge and human columns) plus a JSON summary.
- **Per-step timers** added to the pipeline (recording only); 2 new tests, 90 in total.

### Turn 17 — 2026-11-19 · Credits, dataset review, style test design, Railway, interface redesign

**User** (several short messages):
> so out of 1000 - 923 it the api outage?

> ofc yes cause before the test i wanted to chekc teh dataset

> So if we're gonna keep only English for like the initial run, and I think to keep the tones in, like more formal or more, I don't know, let's call it explanatory, or I don't know, how is it more common to be called. So shall we then also have it as another test point then, like a style assessment, if it's possible or not? What do you think? And then we can do like 500 500, like inside the category, so it also would be too complex, and we, or maybe yeah, 500 of formal, half 500 of less formal. Then I think we can assess up some, I don't know, like 100 from this batch, 100 from this batch, like the determinism according to the style.

> ye make sense also. so we have same 1000 cases for formal and more explanatory style? then im reviering the injetcion prompt and see the piratos trop twise. is that suppose to be like it?

> where can i read mor on the prompt injetcions topics. [...] why thaving a hidden indtruction like shapin explain like you are someome can be harmful to the model? or that is just a simulation, and user can give very harmful hidden indtruction?

> so you think it would make sense to measure latency thu the interface somehow?

> i might dpeloy it on the Railway after all, it would be more familiar for me

> we need to work thu the inetface design. [screenshot of a minimal admin tool] lets do more minimalistic like this

**Agent actions and replies (summary):**
- The 923 failures were not an outage: the Gemini prepaid credits ran out mid-run (`402 RESOURCE_EXHAUSTED`); the runner recorded them as infrastructure errors. The full run waits for a top-up.
- Acknowledged that the run should have waited for the user's dataset review; exported `evals/e2e_cases_review.csv` (all 1,000 cases with gold text, facts and empty verdict columns).
- Style assessment: recommended running the same cases in both styles (paired) rather than a 500/500 split, plus deterministic readability checks and a blind judge/human comparison of 100 + 100 answers.
- Explained the two pirate cases (an override and a hidden instruction inside a real question: harmless "canaries" that show whether the bot can be steered), what real injections could do in this app, and reading material (OWASP LLM01, Simon Willison, Greshake et al. 2023, Perez & Ribeiro 2022, NIST AI 100-2, Lakera Gandalf). Linked Art. 15(5) on adversarial inputs.
- Latency: server-side per-step timings already exist; proposed showing the breakdown in the UI and measuring through the deployed URL with a script, plus cold start.
- Deployment target changed to Railway (recorded in PLAN).
- **Interface redesign** in the style of the reference: left sidebar with navigation and the documents as nested items, slim top bar with a sidebar toggle and a light/dark switch, bold page titles, white bordered cards, segmented control for the answer style, bordered chips for citations and metadata, Inter font, light by default. Checked all pages in the browser, light and dark.

**User:**
> looks ver good

**Agent reply (summary):** listed what waits on the user (Gemini top-up, dataset review in `evals/e2e_cases_review.csv`, Mistral key, how to deploy to Railway) and what can be built without credits (Dockerfile and Railway setup, per-step latency line in the chat, readability and jargon checks).

### Turn 18 — 2026-11-20 · Methodology review; local run

**User:**
> read the METHODLOFY file

> good, okay, so continue to collect the data on our communication. procide the locally deployed site so i cna chekc in the browser

**Agent actions:**
- Read `docs/METHODOLOGY.md` and checked it against the repo. Found it stale in six places: the end-to-end set was still "planned, ~100 cases" (it is 1,000 cases, 700 dev / 300 test), 88 tests (now 90), Hugging Face Space as the deployment target (now Railway), the style comparison not yet designed (now paired, same cases in both styles), the timeline stopping at Turn 15, and the reason the end-to-end numbers are missing (now the Gemini credits and the dataset review, not missing code).
- Updated the methodology and this log accordingly.
- Started the app locally (`uvicorn app.api:app --port 7860`) for the user's browser check.

### Turn 19 — 2026-11-20 · Judge choice, budget, Mistral pricing, smoke run

**User** (several short messages): asked whether $4 of Claude credits could grade 2,000 interactions with context; whether Haiku is stronger than the generation model; how much Mistral would cost; asked again about Pinecone; chose Sonnet as the judge after the comparison; added the Mistral and Claude keys; asked for a 10-case sample before the full Legal-detail run, with a CSV to review: case ID, topic, check type, the Gemini answer, the LLM score (with or without reasons, whichever is cheaper), latency per step.

**Agent actions and replies (summary):**
- The "Connection problem" in the UI was the local server stopping with the previous session, not credits.
- Judge cost estimated from measured token sizes (gold text ~85 words, answers ~250-350 words, ~2,800 input tokens per case): Haiku 5.5 ~$0.45, Sonnet 5.5 ~$6 (~$3 with the Batch API), Opus 5.5 ~$18 per 1,000. Reasons cost almost nothing (input dominates). Haiku is not necessarily stronger than the answer model; the judge needs independence (a different family) and enough skill to catch missing exceptions, not to be stronger. **Decision:** Sonnet 5.5, thinking off, grades all 1,000; Opus 5.5 re-grades 100 for an agreement check; the user's scores are the final reference.
- Mistral pricing read from the docs pricing page (2026-11-20): Mistral Large 4 $0.70 / $2.10, Small 4 $0.15 / $0.60 per 1M tokens; ~$3 for 2,000 answers on Large 4.
- Pinecone again: not needed at 893 vectors (2.7 MB, in memory, ~1 ms); belongs in the production design for many documents, frequent updates or several servers.
- Gemini returned `402` until the top-up reached the key's project.
- Built `evals/judge_e2e.py`: Claude judge (Sonnet 5.5 default, thinking off, JSON schema output: one-line reason first, then correctness, completeness, grounding, citations, clarity, overall on 1-10, 0 = not applicable), real-time or Batch API; writes a judged full CSV and a compact review CSV (`your_score`, `your_notes` columns for the user).
- Smoke run, Legal detail, one case at a time: 13 cases (one per topic, four provision questions); all passed the deterministic checks; judge overall 9-10 on all. Gemini cost $0.0017 per case; judge $0.006 per case real-time. Latency: answers first token p50 3.05 s, total p50 3.7 s; floor refusal 0.35 s; guard refusal 1.2 s. 3 of the 13 cases are from the test split (disclosed).

### Turn 20 — 2026-11-20 · Why the answer model is 3.8 Flash

**User:**
> So I want to log the fact that we have selected Gemini 3.0 Flash above Gemini 3.5 Flash Lite based on the fact that we have been intending to build multilingual rack. So that is still an intention if we have enough time to work on it. For my job, we have seen that Gemini 3.8 is behaving better with the translation and being like in multilingual context in general compared to Gemini 3.5, while Gemini 3.5 is good with the summarization, rewriting, etc, etc. So solely based on this fact, this model was selected over another one.

**Agent actions:** recorded the rationale in `METHODOLOGY.md` §6 ("3.0 Flash" read as `gemini-3.8-flash`, the answer model), marked as based on the user's professional experience rather than a measurement in this project.

### Turn 21 — 2026-11-20 · Review of the smoke CSV; judge output settled

**User:** asked what `split`, the judge aspect columns, `judge_reason` and `path` mean; first asked to simplify the judge to one 0-10 score with a reason, then decided to keep the five aspect scores; asked what the `_judged.csv` file adds.

**Agent actions:**
- Explained the columns (dev/test split, the five aspects, the reason, the outcome path, `ms_*` = per-step latency).
- Briefly switched the judge to one score, then restored on the user's decision: five aspects (correctness, completeness, grounding, citations, clarity; 1-10, **empty when not applicable**, e.g. refusals, so an empty cell is never confused with a bad score) plus **overall 0 (worst) to 10 (perfect)** and a one-line reason.
- Removed the separate `_judged.csv`: the judge now fills the judge columns of the run CSV itself; only a sample or tagged re-grade (the Opus check) gets its own file. Two files per run: the full run CSV and the compact review CSV.
- Judge cost with five aspects: $6.44 per 1,000 real-time (~$3.20 with the Batch API). Observed: the judge sometimes writes "No issues." next to a 9.

### Turn 22 — 2026-11-20 · Judge: Sonnet, thinking off; full run 1 (Legal detail)

**User:** chose Sonnet 5.5 as the judge after asking whether a Google model would be better; asked to log the reasons; asked to run the 1,000 cases without redoing the 13 smoke cases; asked why thinking is off and decided to keep it off.

**Agent actions:**
- Logged the judge choice (three reasons: self-preference, a fair Gemini vs Mistral comparison, capability measured rather than assumed) and the thinking-off rationale in `METHODOLOGY.md` §8.5. Stated that Sonnet being stronger than the answer model was not measured.
- Added `--reuse` to the runner: cases from an earlier run of the same configuration are kept, not re-run (13 smoke cases), recorded in the summary.
- Run 1: `gemini-3.8-flash`, Legal detail, one case at a time, 3,930 s, 0 API errors. Deterministic pass: dev 0.877, test 0.903. Latency p50: answer first token 3.3 s (total 4.8 s), guard refusal 1.3 s, floor refusal 0.38 s. Cost $1.79 (Gemini).
- Judge (Sonnet 5.5, Batch API): 1,000 graded, 0 errors, $3.14. Mean overall 9.16; lowest by topic: ambiguous 6.25, not in the Act 6.97, multi-turn 8.50.
- Failure analysis: 37 answers fail only on citation validity, likely the checker being too strict (narrowing a whole-annex chunk to a point; citing a paragraph whose points were retrieved); 14 "not in the Act" questions refused by the guard as off-topic; 15 ambiguous questions answered instead of clarified; 6 injection cases and 3 code cases probably mislabelled (real question answered, injection ignored, no code). No leaks, no obeyed injections, no code output. 35 cases fail the deterministic checks but get 9-10 from the judge (mostly citation validity), supporting the checker-strictness reading. The judge wrote "No issues." next to a score below 10 in 67 cases.

### Turn 23 — 2026-11-20 · Why an Opus check if Sonnet is the judge

**User:** "why Opus is we decided with Sonnet?"

**Agent actions:**
- Explained that Sonnet stays the judge for all 1,000 cases. The proposed Opus run only re-grades a random 100 of them to measure how often a stronger model agrees with Sonnet. That is the check promised in reason 3 of the judge choice: Sonnet's capability is measured rather than assumed. If agreement is high, Sonnet's scores stand and Opus is not used again. If it is low, the 100 disagreements show where Sonnet is weak, and the user's own review (`your_score`) decides.
- Said the check is optional (about $1.50). Without it, the user's manual review of a sample is the only check on the judge.

### Turn 24 — 2026-11-20 · Completeness score

**User:** "what is the average score of the completeness?"

**Agent actions:** Computed from the run 1 review CSV. Mean 9.11, median 10, over the 657 cases where it applies. The other 343 are refusals or clarifications, which the judge leaves empty. 338 cases score 10, 194 score 9, and 17 score 5 or below. Lowest by topic: multi-turn 8.42, scenario 8.46, rare term 8.62. Highest: definition 9.93.

### Turn 25 — 2026-11-20 · Run 2: the same evaluation with Mistral

**User:** "so shall we do the same now iwth mistral?"

**Agent actions:**
- Added the Mistral provider (`app/llm/mistral.py`), its prices in `app/pricing.yaml`, and the factory hook. Only the answer model changes; the guard, retrieval and prompts stay the same as run 1.
- Smoke tests against the API before writing code: the model list confirmed `mistral-large-4`. Reasoning cannot be switched off on Large 4 ("none" returns a 400), so it runs at "low" like the Gemini answer model. Reasoning comes back as separate chunks in the stream and is filtered out.
- 13-case smoke run (same cases as Gemini): 0 API errors, cost $0.19 per 100 cases (Gemini $0.18). Time to first word was slower: median about 4.9 s (Gemini about 3.0 s), with outliers of 12 s and 27 s. Mistral writes shorter visible answers but spends more output tokens on reasoning. 2 fails: a code case the guard let through this time (Mistral declined the code and answered the legal part, the known mislabel pattern) and one answer missing one of two expected facts.
- Started the full 1,000-case run in the background (sequential, smoke cases reused). The Sonnet judge (batch) follows when it finishes.

### Turn 26 — 2026-11-20 · Opus check dropped; Mistral run is slow

**User:** "we not gonna do the opus check. what is the progress with the mistral now?"

**Agent actions:**
- Recorded the decision in `METHODOLOGY.md` §8.5: no Opus agreement check. The user's own scores on a sample are now the only check on the judge.
- Progress after about 20 minutes: 50 of 987 cases in 869 s, about 17 s per case against about 4.6 s for Gemini in run 1 (first 50 in 228 s). Two probe requests came back in 2-4 s with no rate-limit errors, so the slowness comes from the model's reasoning on long answers, not throttling. Projected total about 4 hours. Kept one case at a time so the latency figures stay comparable with run 1.

### Turn 27 — 2026-11-20 · Progress check

**User:** "what is the progress?"

**Agent actions:** At 19:43, 200 of 987 cases had run in 3,474 s (about 17 s per case, steady). The cases are in dataset order: answer-type cases first, fast refusal categories at the end, as in run 1. Estimated finish around 22:00.

### Turn 28 — 2026-11-20 · Progress check

**User:** "how is the progress"

**Agent actions:** At 20:30, 400 of 987 cases had run in 6,379 s (about 440 by now). The last 50 took 613 s (about 12 s per case), faster than the first 200. 0 errors reported. Estimated finish around 21:30-21:45.

### Turn 29 — 2026-11-20 · Why Mistral is slow

**User:** "so whta is the reason it is so slow?"

**Agent actions:** Compared the 9 smoke cases both models answered, using answer-model output tokens and timings.
- Mistral wrote 2-5 times more output tokens (e.g. 1,116 vs 336) while its visible answers were shorter. The difference is hidden reasoning, which cannot be switched off on Large 4.
- The first word appears only after the reasoning ends: 2.3-10.3 s for Mistral against 1.3-2.5 s for Gemini.
- Normal generation speed is similar (about 70-110 tokens/s). There are occasional stalls on Mistral's side: one case ran at 17 tokens/s and waited 26 s for its first word.
- The full run averages 12-17 s per case, more than the smoke cases suggest. Two possible extra causes are more frequent stalls and the eval's single retry when an answer fails the citation post-check. Both are to be confirmed from the full CSV.

### Turn 30 — 2026-11-20 · Is the comparison unequal (reasoning vs none)?

**User:** "so do you think that the experiemnt is a bit unequal, since gemini do not reason, while misral does"

**Agent actions:** Measured instead of assuming. The thinking-token count is not saved in the run CSVs, so 3 smoke questions were sent through the real pipeline (same prompt and excerpts) with each setting:

| Case | Gemini 3.8 Flash, low | Gemini 3.8 Flash, high | Mistral Large 4, low |
|---|---|---|---|
| e0275 | 0 thinking tokens, first word 1.5 s | 975, 9.4 s | 571, 6.9 s |
| e0618 | 0, 1.4 s | 749, 6.4 s | 346, 6.9 s |
| e0474 | 0, 1.6 s | 1,338, 12.4 s | 668, 9.2 s |

- Confirmed: the comparison is unequal. At "low", Gemini 3.8 Flash does not think at all, while Large 4 cannot go below about 350-670 thinking tokens per answer.
- The current run is still a valid comparison of each model at its lowest available setting. It is what a user would get, but it mixes the model with the effect of reasoning.
- Checked the alternatives: `mistral-medium-3-5` and `mistral-small-latest` answer with 0 reasoning tokens.
- Recommended: let the Large 4 run finish (more than half done), then run a no-reasoning Mistral (Medium 3.5) as the like-for-like comparison with Gemini at "low". This gives Gemini vs Mistral on equal terms, plus whether reasoning helps on this task.

### Turn 31 — 2026-11-20 · Why no reasoning on the Gemini side; progress

**User:** "why we dont use reasoning on the gemini side tho? plus what is the proegress now?"

**Agent actions:**
- Honest answer from the docs: the answer model was set to thinking `low` at setup (PLAN.md, METHODOLOGY.md §6) because it is the lowest level `gemini-3.8-flash` accepts ("minimal" is rejected), to keep latency and cost down. It was a default, not a measured decision. That "low" means 0 thinking tokens in practice was only found in Turn 30. Whether reasoning improves answer quality on this task has not been tested for either provider.
- Where reasoning could help: run 1's weak spots (ambiguous 6.25, not in the Act 6.97) come mostly from the guard routing, not from the answer model. Answer quality where the model did answer is already high (completeness 9.11, correctness 9.48). The Large 4 run will show whether reasoning adds anything.
- Progress at 21:18: 550 of 987 in 8,604 s, about 12 s per case. Estimated finish around 22:00.

### Turn 32 — 2026-11-20 · Run 3: Gemini with reasoning, in parallel

**User:** "can we run now gemini with reasoning on in parallel? i wann ahave the more or less equal comparisom"

**Agent actions:**
- Probed Gemini at `medium` on the same 3 questions: 644 / 650 / 1,061 thinking tokens, first word 6.1-8.3 s. This is the closest to Mistral `low` (571 / 346 / 668). `low` gives 0 and `high` about twice Mistral's count. Chose `medium`.
- Started run 3 in the background: 1,000 cases, `ANSWER_THINKING=medium`, otherwise identical to run 1 (tag `think-medium`), one case at a time. It runs alongside the Mistral run; memory is fine (11 GB available). Confirmed `.env` does not override the thinking setting.
- Logged in METHODOLOGY.md §6 how runs 1, 2 and 3 compare: 2 vs 3 is the provider comparison with reasoning on, and 1 vs 3 shows what reasoning adds for Gemini.

### Turn 33 — 2026-11-20 · Local app started for interface review

**User:** "now gimme start and lets run it up, and i will review the interfcae"

**Agent actions:** Started the app at http://127.0.0.1:7860 (uvicorn, default settings: `gemini-3.8-flash`, thinking `low`, guard `gemini-3.5-flash-lite`). It responded within 1 s. The two eval runs (Mistral, Gemini medium) keep running alongside it.

### Turn 34 — 2026-11-20 · Run 2 (Mistral Large 4) finished

**Agent actions (background notification, no user message):**
- Run 2: 1,000 cases, 0 API errors, 11,629 s (3.2 h; run 1 took 1.1 h). Deterministic pass: dev 0.906, test 0.917 (Gemini run 1: 0.877 / 0.903). Answer cost $1.98 ($1.79 for Gemini).
- Latency on the 682 cases both runs answered: first word p50 6.8 s, p90 26.2 s, max 103 s; 105 cases over 20 s (Gemini: p50 1.8 s, p90 2.2 s, 1 case over 20 s). Median answer-model output 548 tokens vs 214, mostly hidden reasoning. No case shows a second answer call, so retries are not the cause. Turn 29's two candidate causes are settled: reasoning sets the baseline delay, and Mistral-side stalls cause the long tail.
- Started the Sonnet batch judge on run 2.

### Turn 35 — 2026-11-20 · Run 2 judged: Mistral vs Gemini (no reasoning)

**Agent actions (background notification, no user message):**
- Sonnet batch judge on run 2: 1,000 graded, 0 errors, 245 s, $3.02.
- On the 683 cases both runs answered, overall quality is a tie: 9.07 vs 9.07. Mistral is better on 146 cases and Gemini on 125; 412 are equal. Aspects (Mistral / Gemini): correctness 9.48 / 9.52, completeness 8.89 / 9.14, grounding 9.70 / 9.65, citations 9.63 / 9.56, clarity 9.34 / 9.05. Mistral writes shorter, clearer answers that leave out more; Gemini writes fuller ones.
- Mistral's higher deterministic pass rate (612 vs 593 of the shared cases) comes entirely from `citations_valid` (614 vs 580), the check already suspected of being too strict, because Gemini narrows citations to points. On expected facts Gemini is ahead (615 vs 601).
- Conclusion so far: Mistral with reasoning gives no quality gain over Gemini without reasoning, at 3-4 times the time to first word and 11% more answer cost. Run 3 (Gemini with reasoning) will show whether reasoning helps Gemini.

### Turn 36 — 2026-11-20 · Run 3 progress

**User:** "alright what is the progress on gemini with reasonng noiw"

**Agent actions:** At 22:05, run 3 had done 200 of 1,000 cases in 1,937 s (about 225 by then), about 9.5-10 s per case and steady, with 0 errors reported. Run 1 took about 5.3 s per case on the same stretch, so reasoning roughly doubles the time per case. The fast refusal categories are at the end. Estimated finish around 23:30, then the Sonnet judge (about 5 min).

### Turn 37 — 2026-11-20 · Run 3 progress

**User:** "what is the progress now?"

**Agent actions:** At 22:27, 350 of 1,000 cases had run in 3,363 s (about 360 by then), steady at about 9.6 s per case, 0 errors reported. Estimated finish still around 23:30.

### Turn 38 — 2026-11-20 · Run 3 progress

**User:** "what is the progress now"

**Agent actions:** At 22:55, 500 of 1,000 cases had run in 4,809 s (about 535 by then), 0 errors reported. About 115 answer-heavy cases remain, then the fast refusal categories. Estimated finish around 23:30.

### Turn 39 — 2026-11-20 · Run 3 finished and judged: three-way comparison

**Agent actions (background notifications, no user message):**
- Run 3 (Gemini, thinking `medium`): 1,000 cases, 0 API errors, 7,549 s; answer cost $3.46. Sonnet judge: 1,000 graded, 0 errors, $3.14.
- Compared runs 1-3 on the 676 cases all three answered. Judge overall: 9.12 (Gemini low), 9.09 (Gemini medium), 9.13 (Mistral). First word p50: 1.8 / 6.3 / 6.8 s. Answer cost: $1.79 / $3.46 / $1.98. Full table in METHODOLOGY.md §6.
- Finding: reasoning adds no measurable quality on this task, for either provider. Gemini medium vs low: better on 123 cases, worse on 126 (noise-like). The deterministic gains of runs 2 and 3 come from the strict citation check, not from facts.
- Recommendation: keep Gemini 3.8 Flash without reasoning for production.

### Turn 40 — 2026-11-21 · Answer-model table on the Evaluation page; selected rows in green

**User:** "lets add this table to the Evaluation page. in the header indicate the precise names of the gemini model. then overall: … lets add some liht geen highlight to the row, to indicate that this model was finally selected forthe system. then in the tabe of the generation model's comparison - hid eth 5 criterion … so if user would only see them is they expand the judge poverall record."

**Agent actions:**
- `evals/summarize_models.py` (new) computes the table from the three run CSVs on the cases all three answered and writes `evals/results/model_selection.json`, so the page shows computed values, not typed ones. `/api/evals` now returns it as `generation`.
- Evaluation page (`app/web/app.js`): new "Answer model" block replacing the "pending" placeholder. The column headers carry the exact model IDs (`gemini-3.8-flash` twice, with thinking low / medium, and `mistral-large-4`, reasoning low). The selected column is tinted green and labelled "selected". "Judge overall" is a toggle row (mouse or keyboard): the five judge aspects (correctness, completeness, grounding, citations, clarity) and expected facts found stay hidden until it is expanded. Visible rows: judge overall, first word median / 90% / slowest, answer cost.
- `styles.css`: a light green `--ok-soft` token (light and dark theme). Rows already marked as the final choice (gemini-embedding-2, the product retrieval configuration, structural chunking) now get the green background as well as bold.
- Page description updated: it no longer says "no LLM judge".
- Restarted the local server and checked in the browser: the table renders, the toggle works, the green highlight is readable in dark mode, and the app logged no console errors.

### Turn 41 — 2026-11-21 · "Generation model"; sidebar Summary with TTFT and speed

**User:** "Answer model - rename to Generation model. [the sidebar Models section] this section rename to the summary. keep what we already have there. add the facts as latency tothe firs word (thereshall be more appropriate name as an abbreviation for it), tokens per second...?"

**Agent actions:**
- Renamed the Evaluation block to "Generation model". Its latency rows are now "TTFT" (time to first token). The note says this TTFT starts at the generation-model call, so it excludes the guard and retrieval.
- Sidebar: "Models" became "Summary"; the existing lines are kept, with "Answer" renamed "Generation" for consistency. Added three measured facts from run 1 (production setup, 688 answers): TTFT 3.3 s (median, from sending the question to the first token, including guard and retrieval; the full definition is in a hover tooltip), Speed 154 tok/s (median generation speed after the first token; one-chunk answers excluded), Full answer 4.8 s (median).
- The figures are computed in `evals/summarize_models.py` (`production` in `model_selection.json`) and served by `/api/info`, not typed in.
- Restarted the server and checked in the browser. A first screenshot showed the old sidebar from the browser cache; the served HTML was correct, and after a reload the sidebar shows the new section.

### Turn 42 — 2026-11-21 · LLM-as-judge component charts

**User:** "below the block of the generation model, lets add a new block on LLM-as-Judge assessment components. there we would add 5 intercative barchart per assess criterion: correctness, completeness, grouping, citations, clarity (what we have had actually 6? ) and expected facts. and compare the 3 mdoels this way and remove it from the table. then if we have 6 - do in 2 rows - 3 charts in the row."

**Agent actions:**
- Confirmed there are 6: the five judge aspects (correctness, completeness, grounding, citations, clarity) plus "expected facts found", which is the deterministic check, not the judge. The block labels it that way.
- New block "LLM-as-judge assessment components" below the generation-model table: 6 small bar charts, 3 per row (2 per row under 1,000 px, 1 under 600 px). Each chart has the 3 runs as bars from 0 (0-10 for judge aspects, 0-676 for facts), with a direct label and value on every bar, one shared legend with the exact model IDs, and a hover/keyboard-focus tooltip showing the difference from the selected setup.
- Colours: the validated categorical slots 1-3 (blue, orange, aqua), checked with the palette validator against the app's own light (#fff) and dark (#111113) surfaces, all-pairs. All checks pass. Aqua is below 3:1 contrast on white, so every bar carries a visible text label.
- Removed the five aspects and facts from the table; it now shows judge overall, TTFT and cost. The expand toggle was removed with them.
- Checked in the browser: 6 charts render in 2 rows of 3, the tooltip shows (e.g. "Clarity: 9.35, +0.29 vs selected"), and dark mode is legible.

### Turn 43 — 2026-11-21 · Evaluation log off the page; blind review sheet; next tone test

**User:** proposed next steps: (1) "elaborate whteher we need to keep the evaluation log … i stromgly consider to remove it. perhaps have it as a md file in the project, yet to remove form the interface"; (2) "perfom the qualitative check of approximately 100 responces … include 100 intercations as well as answers of 3 models. we may do the blind assessment … 0 to 10 for each respince"; (3) "the tone mode: shall we process with the testing … in the different tone (explanatory)? shall we do the symmetrical test in that case?"

**Agent actions:**
- (1) Agreed. The page already shows each decision's result in its own table, and the 3,200-word log repeats them with process detail that suits a repository reader better. Removed the collapsed log from the Evaluation page and replaced it with one line pointing to `docs/EVALUATION_LOG.md`, which stays in the repository.
- (2) `evals/make_blind_review.py` (new) writes `evals/review/blind_review_100.csv`: 100 dev cases that all three runs answered (stratified by topic, at least 2 per topic where available, fixed seed). Each row has the question, any earlier turn, the expected behaviour, the gold provisions and the three answers as A/B/C, shuffled per case, with empty `score_A/B/C` (0-10) and `notes`. The model behind each letter and Sonnet's overall score are in a separate `blind_key_100.csv`, to be opened only after scoring. Dev only, so the frozen test split stays unread. The first draft gave 99 rows (the off-topic topic has only 1 eligible case); the quota now tops up from other topics.
- (3) Recommended against a fully symmetrical three-model run: the reasoning setups showed no gain and are not selected, so tripling the cost would test configurations that will not ship. Proposed instead: Plain style on the selected setup (Gemini, thinking low) only, all 1,000 cases, paired against run 1 (same cases, same model, only the style changes). The judge prompt has to state the intended style first, because "clarity" and "completeness" mean different things for a plain-language answer. Awaiting the user's go-ahead.

### Turn 44 — 2026-11-21 · Plain style test: prompt, pairing, budget

**User:** "1) what prompt change shall we expect with the tone change? 2) shall w edo the symmatrical test on te same 1000 quetsions? 3) statement: yes that is rght lets do only gemeni 3.8 then. 4) how much ypou think i would need to have (balance wise on the claude api) for the assessment?"

**Agent actions:**
- (1) Answer prompt: only rule 3 changes, and it is already built (`app/chat/prompts.py`, `STYLES["plain"]`). It asks for a direct answer in one or two short sentences, at most four bullets, about 150 words, everyday words, each defined term explained once, no headings or bold, and never dropping a condition, exception, date or amount. The grounding rules (excerpts only, citations, no code, not legal advice) are identical. Judge prompt: to add the intended style to every case and a style-aware reading of clarity and completeness (plain = understandable to a non-lawyer; a simplified condition counts, a dropped one does not).
- (2) Yes: the same 1,000 questions, paired with run 1, so every difference comes from the style (as planned in METHODOLOGY.md §8.4). For symmetry on the judging side too, recommended re-grading run 1 with the same updated judge prompt, so both styles are graded by identical instructions.
- (3) Gemini 3.8 Flash (thinking low) only; the user confirmed.
- (4) Estimate for Claude: about $3.1 per 1,000 graded cases (batch). Plain run $3.1, plus re-grading the Legal run $3.1, plus a 13-case prompt check (cents), about $6.5 in total. Recommended a $10 balance for margin.

### Turn 45 — 2026-11-21 · Plain style run started

**User:** "ok lets start then"

**Agent actions:**
- Started run 4: Gemini 3.8 Flash (thinking low), Plain language style, all 1,000 cases, one at a time.
- Made the judge prompt style-aware (`evals/judge_e2e.py`): each case states its intended style. A style section defines legal and plain, says the chosen style itself is never penalised, and explains how clarity and completeness apply to plain answers.
- Tested on the 13 Legal smoke cases (real-time, $0.09): 7 grades moved by +1 (e.g. overall 9 to 10), none down. This may partly be the judge's run-to-run variation. Either way it confirms both styles must be graded with the same prompt.
- Started the re-grade of the Legal run with the new prompt (batch, tag `judgev2`). The original grades, which the Evaluation page uses, are kept.
- The Plain run will be graded with the same prompt when it finishes.

### Turn 46 — 2026-11-21 · Legal run re-graded with the style-aware judge

**Agent actions (background notification, no user message):**
- Re-grade: 1,000 graded, 0 errors, 186 s, $3.37.
- Old vs new prompt on the same Legal answers: overall 9.16 vs 9.12 (79 cases up, 123 down), completeness 9.11 vs 8.98, correctness 9.48 vs 9.42, grounding 9.64 vs 9.64, citations 9.52 vs 9.48, clarity 9.02 vs 9.03.
- The smoke check's "+1 on 7 of 13" did not hold on the full set, so it was mostly noise. A useful by-product: about 20% of cases change their overall grade between two gradings of the same answer, so differences between runs under about 0.05-0.1 points are within the judge's own variation. The Legal vs Plain comparison uses the re-graded (`judgev2`) Legal scores.

### Turn 47 — 2026-11-21 · Not-legal-advice disclaimer above the chat

**User:** "1) what is the progress now? 2) in the question 8, 2 models add at the end 'This is not a legal advice'. I do like it. I think it would be worth adding some kinda of the disclaimer. above the chat: This is not legal advice, it is an AI-based chatbot. AI do not knowall the detail of your situations and all other laws. This chatbot cannot be reesponsible for your actions. Infomation purpose only. etc."

**Agent actions:**
- Progress: Plain run at 250 of 1,000 at 12:04 (about 4.7 s per case), finish expected around 12:50.
- Added a disclaimer box between the page header and the chat (`app/web/index.html`, `styles.css`), based on the user's draft: not legal advice; an AI chatbot, for information only; answers from the AI Act text alone; does not know the user's situation, other EU or national laws, guidance or later amendments; can make mistakes; check the cited provisions and consult a lawyer; the user remains responsible for their decisions. Styled as a muted warning note with an icon, in both themes.
- Removed "Informational only, not legal advice." from the source line under the page title (`app/config.py`), since the box now says it. Restarted the server; 90 tests pass.
- The in-answer line stays as it is: the answer prompt (rule 6) already adds a one-sentence "not legal advice" when the user asks about their own situation, which is why it appeared in that question.

### Turn 48 — 2026-11-21 · Chat fits the screen; "Explanatory"; privacy and feedback

**User:** "1) now the full site does not firt th web age in 100% scale … the usertwould need to scroll down to see the text field and button … fix the layout. 2) how isthe progress now with the explanatory tone? also rename the toggle form the plain language to explanatory … 3) lets evaluate the idea of teh human assessment? what the act itelself sying for the compaie of the collection of the users data? i am keen on not to store the intercation anywhere. and add a messgae on it as well … below the sources section we may add teh feedback section with the text field … Your data is not stores. We improve thu yourfeddback … how doe sthat douns?"

**Agent actions:**
- (1) Cause: the chat card height was a fixed estimate (`100vh - 168px`), and the new disclaimer made the header taller. On screens at least 901 px wide and 600 px tall, the chat tab is now a flex column that fills exactly the space below the top bar; only the message list scrolls. Measured in the browser at 1604×1152, 1920×950, 1280×700 and 1366×650: the composer is fully visible and the page does not scroll in every case. Narrow and short screens keep the previous scrolling layout.
- (2) Plain run at 900 of 1,000 at 12:44. Renamed the visible toggle from "Plain language" to "Explanatory" (tooltip: "Explained in everyday words for non-lawyers, same citations"). The internal key stays `plain`, so evaluation files and code are unchanged.
- (3) Checked rather than assumed:
  - The AI Act does not itself regulate collecting users' chat data. Art. 2(7) says EU data-protection law (the GDPR and the ePrivacy Directive) applies and is not affected. The Act's relevant duty here is Art. 50(1): people must be told they are interacting with an AI system, which the new disclaimer covers.
  - Current app: every turn is written permanently to SQLite (`data/app.sqlite3`: question, rewritten question, answer, citations, cost), with no deletion, so a page reload can restore the conversation. Server logs do not contain question text. Questions are also sent to Google's Gemini API to be answered. So "your data is not stored" would be false today.
  - Proposed: keep conversations in server memory only, deleted after 30 minutes of inactivity or on "New conversation", never written to disk; say so truthfully, including that questions go to Google's Gemini API. Feedback text is itself stored data, so the notice must say feedback is stored (text only, no conversation, no IP) and ask users not to include personal details. Also suggested an optional rating (helpful / not helpful) next to each answer as a source of real-user quality data. Decisions requested from the user.

### Turn 49 — 2026-11-21 · Privacy idea parked; grading in progress

**User:** "fair haha. okay lets log this idea and move in, what is explanatory tone assesment progress"

**Agent actions:** Logged the privacy and feedback proposal as open item 3 in `docs/PLAN.md` §8 (facts checked, proposal, open storage question), not scheduled. The Explanatory run finished at 12:46 (1,000 cases, 0 errors, $1.74). Its Sonnet batch grading (style-aware prompt) was submitted and still processing.

### Turn 50 — 2026-11-21 · Style test result: Explanatory underperforms

**Agent actions (background notification, no user message):**
- Sonnet graded the Explanatory run: 1,000, 0 errors, $3.37.
- Compared with Legal detail (re-graded with the same prompt) on the 683 cases both answered. Judge overall 8.54 vs 9.00 (Explanatory better on 82, worse on 315). Correctness 9.11 vs 9.46, grounding 9.27 vs 9.65, clarity 8.16 vs 9.05. Expected facts 599 vs 615 (17 lost, 1 gained). Median words 119 vs 127, Flesch reading ease 25 vs 19, legal-jargon phrases 0.16 vs 1.15 per answer, citations 6 vs 5 per answer. TTFT and cost unchanged.
- Read a random sample of the judge's reasons where clarity dropped: "slightly dense for plain style", "runs past the plain-style limit (about 190 words, four dense bullets)", and paraphrases that slightly overstate or generalise the Act. Keyword count over all 435 drops: bullets 143, omissions 92, length 63.
- Conclusion: the explanatory prompt removes jargon but does not simplify enough, and paraphrasing costs some accuracy. Recorded in METHODOLOGY.md §8.4 with the table. Recommended keeping Legal detail as the default and iterating the explanatory prompt on a small dev sample before any new full run.

### Turn 51 — 2026-11-21 · Answer-style comparison on the Evaluation page

**User:** "interesting okay, add it to the eval page"

**Agent actions:**
- `evals/summarize_styles.py` (new) computes the Legal vs Explanatory comparison from the two run CSVs and their judge files (paired: aspect means only over cases where both styles have a score) and writes `evals/results/style_comparison.json`; `/api/evals` serves it as `styles`.
- New "Answer style" block on the Evaluation page, below the judge charts: one table with Legal detail (green, labelled "default") and Explanatory. Rows: judge overall and the five aspects (clarity labelled "against the style's aim"), expected facts, words, words per sentence, Flesch reading ease, legal-jargon phrases, citations per answer, TTFT and cost. The note states the setup, the clarity caveat and the conclusion.
- The first edit command was stopped by a Claude Code safety check (it could not parse an inline script; nothing ran) and was redone from a script file. Restarted the server and checked in the browser; 90 tests pass.

### Turn 52 — 2026-11-21 · Blind human review unblinded

**User:** shared the Google Sheet with the blind review scores: "check out the results of the blind assessmen"

**Agent actions:**
- Read the scores, IDs and notes columns only (read-only); 99 of 100 cases scored (e0892 empty); one note ("C contradicts", e0003). Saved them to `evals/review/blind_review_100_scores.csv` and unblinded with the key in `evals/analyze_blind_review.py` (new; output `blind_review_100_results.json`).
- Human means: Gemini low 8.82, Gemini medium 8.99, Mistral 9.05. Sonnet on the same answers: 9.13, 9.11, 8.95, the opposite order. Mistral beat Gemini low 45-27 (sign test p = 0.044; not significant after correcting for three comparisons).
- Judge vs human per answer: Pearson 0.09 (0.12 on answer-type questions), 223 of 297 within 1 point, judge more lenient (9.06 vs 8.95).
- Largest gaps: ambiguous questions answered conditionally (judge 2-3 by its label, user 8-10) and an "off-topic" open-source question the Act does cover (judge 3, user 9). These point to strict dataset labels, not bad answers.
- Recorded in METHODOLOGY.md §8.5, with the consequences: the judge is fit for behaviour failures and large gaps, not for ranking near-equal setups; the generation choice is a latency vs preference trade-off for the user.

### Turn 53 — 2026-11-21 · Wrap-up of the evaluation phase; architecture link

**User:** "1) remove this statement - The full evaluation log … is kept in the repository as docs/EVALUATION_LOG.md. then i do plan to mrge the focal points of the methodlofy and plan and conversation log into the common tab of the agentic usage, but i will clarify a bit laterr on it. i do feel like that would be it actually, and plan to do couple of the tries myself, will draw the full schema of the systme manually and then we will go thu teh agentic usage tab … now - provide me the limk to artifact where we have had the schema draw for the 1st version of the systme"

**Agent actions:**
- Removed the pointer line to `docs/EVALUATION_LOG.md` from the Evaluation page (the file itself stays in the repository).
- Found the architecture artifact: https://claude.ai/artifact/4jGZkPeZAWUN1FrqjVUVEC, first published 2026-11-19 07:00 and updated the same evening with the multilingual flow (section 6). A second artifact with the same title (`UUJ7v3EMBuB27rwVaeXeQD`) is an accidental duplicate from that evening's first publish. The local source is `docs/architecture.html`.
- Noted the user's plan: merge the key points of the methodology, plan and conversation log into the Agentic usage tab later (details to follow); the user tries the system and draws the full schema by hand first.

### Turn 54 — 2026-11-21 · Walking through the scheme: injection handling

**User:** "ok so lets go step by step in the scheme: inhection tets is the cod ebaed check, if code do not deteect injetcion, the query oe sto another check if it fails, what is returne dto the user?"

**Agent actions:** Traced the code (`app/guards/prefilter.py`, `app/chat/pipeline.py`, `app/chat/prompts.py`, `app/web/app.js`) instead of answering from memory. An injection meets up to five layers. The code-based pre-filter (English regex) returns a fixed injection reply with no model call. The relevance floor (first turn only) and the guard (Flash-Lite, which labels "attempts to change your instructions" as out) both return the same out-of-scope reply. If the guard itself errors, the request fails open to "in". An injection hidden inside a real question reaches the answer model, whose rules make it answer only the legal question from the excerpts. The post-check removes code blocks and marks invalid citations with a badge, and the browser replaces the streamed text with the cleaned text. In the four 1,000-case runs no answer obeyed an injection or leaked the instructions.

### Turn 55 — 2026-11-21 · The checks run one after another

**User:** "okay, so you mean that all 5 checks are happening at the same time?"

**Agent actions:** Clarified: the checks run in sequence, cheapest first, and the first one that stops a message ends the request. Later steps never run, so a blocked message costs only the steps before it. Per-step medians from run 1: pre-filter ~0 ms, floor 0.37 s total (refusal at the floor), guard refusal 1.3 s total, answer TTFT 3.3 s. The post-check runs after the full answer, in milliseconds, with no model call.

### Turn 56 — 2026-11-21 · How the floor and "out of scope" are decided, with examples

**User:** "ok so how we determine the relevancy floor? and how we determine out of scope? show one sampels from the 1000 test intercations"

**Agent actions:** Explained from `evals/calibrate_floor.py`, `relevance_floor_gemini2.json` and the guard prompt, with real cases from run 1.
- Floor: the question is embedded and compared with all 893 chunks, and the best cosine similarity is kept. The threshold is calibrated, not guessed: the lowest dev in-scope similarity (0.676) minus a 0.03 margin, rounded down, gives 0.64. It blocks 13 of 15 calibration off-topic questions and 0 of 50 in-scope (0 of 25 on the held-out test). Near-domain questions (GDPR, US AI policy, up to 0.697) pass it on purpose and are left to the guard. Run 1 floor refusals scored 0.46-0.639.
- Out of scope: the guard (Flash-Lite) labels in / out / ambiguous by its prompt's definitions.
- Examples: e0908 (sock news anchor, similarity 0.50, floor); e0772 (EU Copyright Directive, 0.739, passes the floor, guard says out); e0161 (Commission asking for GPAI documentation, 0.829, guard in, answered with Art. 91 citations); e0057, one of 3 in-scope questions wrongly refused (EDPS fines on EU agencies, Art. 100; the guard took it for a GDPR question).

### Turn 57 — 2026-11-21 · Is relevance just vector similarity?

**User:** "so the relevance is basically detemined by the vector simialrity, is that right?"

**Agent actions:** Confirmed from `app/retrieval/search.py` (`retrieve()` returns `ds.max()`): the floor uses only the highest dense (embedding) cosine similarity between the question and any chunk. BM25 and the reference resolver are not part of it, and if the embedding call fails, the floor is skipped and the guard still runs. Clarified that this is only the first of two relevance gates. The second, the guard, is a model's judgement, because similarity measures topic closeness, not scope (the Copyright Directive question scored 0.739). The search that picks the excerpts is a separate, hybrid ranking (resolver + BM25 + embeddings).

### Turn 58 — 2026-11-21 · Score exactly at the floor

**User:** "is the score is equal to 0.64 would it go further or rejected"

**Agent actions:** From `app/chat/pipeline.py:81` (`top < self.r.relevance_floor`): only scores strictly below 0.64 are refused, so exactly 0.64 passes to the guard. Exact ties are practically impossible with unrounded float similarities; the highest refused score in run 1 was 0.639.

### Turn 59 — 2026-11-21 · Drawing the floor check (F2) in the user's diagram

**User:** "how may i represnet on the diagramme that on F2 check the user query is being truend into teh vector and compared with the vectors of tha target docs?"

**Agent actions:** Suggested a notation with an ASCII sketch. An offline lane (Act text → 893 chunks → embed each → vector store, drawn as a cylinder) connects by a dashed line to the online lane (question → F2a embed → F2b cosine similarity against all 893, keep the highest → diamond "top ≥ 0.64?" → refuse or go to the guard). Arrows are labelled with what flows (text, query vector, top similarity), with optional example values (0.50 refused, 0.83 passed). Two notes: the same query vector is reused for retrieval, and on follow-ups the floor applies after the guard, to the rewritten question.

### Turn 60 — 2026-11-21 · How the guard (F3) decides scope and refuses

**User:** "okay then next, F3: how model determined the scope and how rejection is happening"

**Agent actions:** Explained from `app/chat/prompts.py` (`GUARD_SYSTEM`, `GUARD_SCHEMA`) and `app/chat/pipeline.py`.
- One Flash-Lite call (thinking minimal, max 400 tokens, JSON schema) gets the last turns plus the new message. It returns the standalone question, the label (in / out / ambiguous), a clarification (for ambiguous only) and a short reason.
- The code then acts on the label: out gives the fixed out-of-scope reply; ambiguous with a clarification sends that question back; in (or ambiguous without a clarification) continues to retrieval with the rewritten question. If the guard call fails, the request is treated as in.
- Ran the guard live on 3 messages (about 400 tokens in, 60 out, 0.65-0.89 s each). The Copyright Directive question came back out ("not the EU AI Act"). "Do we need a quality management system?" came back in, rewritten to "Do providers of high-risk AI systems need a quality management system under the EU AI Act?". The follow-up "and deployers?" was rewritten to "What are the obligations of deployers of high-risk AI systems under the EU AI Act?" and labelled in.

### Turn 61 — 2026-11-21 · What happens on "ambiguous"

**User:** "and if ambigious - it goes passess the check?"

**Agent actions:** From `pipeline.py`: "ambiguous" stops the request and sends the guard's clarifying question back; no retrieval and no generation call. The user's reply arrives as a follow-up, and the guard then rewrites it with the earlier message as context. The code falls through to answering only if the label is "ambiguous" but the clarification field is empty. In run 1 that never happened: all 22 ambiguous labels came with a clarification (e.g. e0650 "Is this legal in the EU now?" → "Could you please specify what AI system or practice you are asking about?").

### Turn 62 — 2026-11-21 · Are refusals deterministic?

**User:** "and if query do not pass it - user recieve deterministic rejection?"

**Agent actions:** Confirmed from the code: "out" returns the fixed `OUT_OF_SCOPE` constant, the same text as the floor refusal, so the user cannot tell which step stopped them. The pre-filter replies (injection, code, too long, empty) and the "service unavailable" error are fixed too. The one stop whose text the model writes is the clarifying question on "ambiguous". Its risk is limited: it is one short question from the guard's JSON field, and the guard never sees the Act's text.

### Turn 63 — 2026-11-21 · Validation of the user's hand-drawn scheme (F1-F3)

**User:** "created a scheme folder in the el_chatbot can you chekc and validate the initial part of the scheme" (`scheme/screenshot-2026-11-21_15-00-58-google-chrome.png`)

**Agent actions:** Compared the drawing with `app/guards/prefilter.py`, `app/chat/pipeline.py` and `app/retrieval/`.
- Correct: the order F1 → F2 → F3 → retrieval; F1 binary with a fixed rejection; F2 query vs AI Act embeddings with ≥ 0.64 passing; F3 Flash-Lite returning JSON; "out" giving a fixed rejection; "in" continuing.
- Fixes suggested:
  - the label "similarity < 0.67" should read < 0.64 (0.676 is the calibration minimum, not the threshold);
  - F1 also catches code requests, over-long and empty messages;
  - F3's "0/-1 → deterministic rejection" merges two exits (ambiguous returns a model-written clarifying question, not a rejection);
  - "quality assessment" should read scope classification plus rewrite;
  - the F3 → retrieval arrow carries the rewritten question;
  - retrieval is hybrid (references + BM25 + embeddings).
- Additions suggested: follow-ups skip F2 before F3 and are checked after retrieval; the guard fails open; the floor compares with 893 precomputed vectors and keeps the highest score.
- Correction of Turns 57 and 59: the floor's query vector is not always reused for retrieval. The floor embeds the raw message, retrieval embeds the guard's rewritten question, and query embeddings are cached by text (`app/retrieval/embedders.py`, `lru_cache`), so a second embedding call happens whenever the guard rewrites the question.

### Turn 64 — 2026-11-21 · Why a length cap, and how long

**User:** "why would it reject too long questions? like what is the max possible symbols?"

**Agent actions:** From the code and PLAN.md §2.4: the cap is 2,000 characters (`MAX_INPUT_CHARS` in `app/config.py`), enforced by the input box (`maxlength`) and again by the pre-filter for direct API calls. Reasons: token cost (the message goes to two models), abuse (injections hidden in long filler, deliberately burning API budget), speed, and fit (real questions are short: in the 1,000 test questions the median is 79 characters and the longest 287). Trade-off noted: describing one's own system for "does it fall under the Act?" may need more, and raising the cap is a config change.

### Turn 65 — 2026-11-21 · Does the generation model see the original question?

**User:** "so we dont pass the original query at all? and we use the cheap model to reframe the human request?"

**Agent actions:** Checked `_answer_messages` (`app/chat/pipeline.py:150-164`) and `answer_user_message` (`prompts.py`). The generation model gets the system rules, up to the last 4 turns of history (earlier user messages in their original wording) and, for the current turn, the 8 excerpts plus only the guard's rewritten standalone question; the current original message is not passed.
- Reasons: retrieval needs a self-contained question, the generation model gets the same question the excerpts were found for, the rewrite comes free with the guard call, and the guard is told to keep the meaning and copy questions that are already standalone.
- Weakness confirmed: a bad rewrite (narrowed, dropped nuance) is invisible to the generation model, and the rate is not measured.
- Proposed fix (not built): pass both the original message and the interpretation (~20 tokens), and ask the model to answer the original. This would also let it answer the "ambiguous" questions conditionally.

### Turn 66 — 2026-11-21 · Should we test original vs rewritten question?

**User:** "so you think we should redo experimentm to find out what solution woild be better?"

**Agent actions:**
- Measured first, from run 1's saved `standalone_question` (free): of 688 answered questions, the guard changed 564 (82%) and left 124 unchanged; 504 of the changes were first-turn messages. Most changes are cosmetic ("… under the EU AI Act") or translate lay words into the Act's terms ("conformity checks" → "conformity assessment procedures"), which probably helps retrieval. Narrowing rewrites ("we" → "providers of high-risk systems") are rarer and matter most for vague questions.
- Recommended a small two-part experiment instead of a full rerun: (A) retrieval recall on dev questions with the original vs the rewritten question (embeddings only, about $0); (B) generation with the rewrite only vs original plus interpretation, on about 200 dev cases including all multi-turn and ambiguous ones (about $1-2). Measure facts found and do a human check of the ambiguous ones, since the judge cannot separate near-equal answers. Expected gain is small and mostly on ambiguous questions; a tie keeps the simpler current design. Awaiting the user's go-ahead.

### Turn 67 — 2026-11-21 · Experiment A: search with the original, the rewrite, or both

**User:** "ok, so lets do first A, the consid3r B"

**Agent actions:**
- `evals/rewrite_retrieval_ab.py` (new; result `evals/results/rewrite_retrieval_ab.json`). Production retriever, top 8, using run 1's own rewrites, so no LLM calls. 395 dev first-turn questions with a gold provision; the guard changed 320 of them.
- Recall@1 / @8 / MRR@8: original 0.719 / 0.947 / 0.803, rewrite 0.714 / 0.954 / 0.804, both (original + rewrite as one query) 0.737 / 0.957 / 0.818.
- Paired: rewrite vs original is an exact tie (gold ranked higher 41 vs 40, p = 1.0; found only by one: 7 vs 4). Both vs rewrite: gold ranked higher 34 vs 20 (sign test p = 0.08, not significant).
- Examples cut both ways. The rewrite helps when it maps lay words to the Act's terms ("paperwork" → "technical documentation", "companies using high-risk AI" → "deployers") and hurts when it narrows or reframes ("doesn't fix in time" → "penalties or consequences"). Appending "under the EU AI Act" shifts rankings both ways.
- Conclusion: for retrieval, the rewrite neither helps nor hurts on average. Combining both is slightly better (+2.3 pp recall@1, +1.4 pp MRR) at no extra cost (one query, one embedding), but on dev only and not significant. Changing it would need one confirming run on the frozen test split.

### Turn 68 — 2026-11-21 · Keep the rewrite; what the generation step receives

**User:** "ok mendwhile i search more info on it and it does seems like an effective solution. okay lets keep it this way now, we will explain more in the meth on it. then now im doing the LLM generation step in teh diagramme: how many embeddings form teh article we pass - top k?"

**Agent actions:**
- Recorded experiment A in METHODOLOGY.md §5 (retrieval table, row "A Query text"): results, the user's decision to keep the rewrite, and "both" as an untested-on-test candidate.
- Answered from `app/config.py` and `pipeline._select`: top_k = 8 excerpts. On follow-ups, up to 3 chunks cited in the previous answer are added (citation carry-over), and a 3,000-word context budget applies. Run 1: median 8 excerpts per answer, range 8-11; median generation input 1,698 tokens. The model receives the excerpts' text with their labels, not embeddings; embeddings are used only to find them.

### Turn 69 — 2026-11-21 · Where the history comes from

**User:** "history turns passed from teh db?"

**Agent actions:** Confirmed from `pipeline._history` and `memory.history`: for each new message the last 4 turns (up to 8 messages) of the session are read from SQLite. The guard gets them with user turns in their rewritten form, each cut to 500 characters. The generation model gets the original user wording and only answers and clarifications (refusals dropped, strict user/assistant alternation). Each reply is written back to SQLite afterwards; "New conversation" starts a new session ID. Linked to the parked privacy item (PLAN.md §8): this is the store that would move to memory.

### Turn 70 — 2026-11-21 · The current turn is the rewritten question

**User:** "dont mdoel received alsow the rewritten query"

**Agent actions:** Clarified the previous answer: "original wording" applies to earlier turns from the history. For the current turn, the generation model receives only the guard's rewritten question, together with the 8 excerpts. Listed the four inputs for the diagram: system rules (prompt), last 4 turns in their original wording (SQLite), top 8 excerpts (retrieval), and the rewritten question (guard, the same text retrieval searched with).

### Turn 71 — 2026-11-21 · The post-generation check (F5)

**User:** "okay, so then - after model generated teh answer - what post generation check systme performs?"

**Agent actions:** Explained from `pipeline.postcheck`, `app/chat/citations.py`, `_finish_answer` and the UI:
- Code only, milliseconds. Four checks: code blocks replaced with "[code removed]"; each citation validated against the labels of the excerpts sent (a narrower sub-point of a sent excerpt counts as valid; anything else is invalid); no citation unless the answer says the Act does not address it; truncation at the output limit.
- Results appear as badges; valid citations become links and are marked in Sources.
- It does not block, retry or judge correctness. The retry-once exists only in the unused non-streaming `ask()`; both the app and the eval runner use `stream()`.
- Run 1 (688 answers): invalid citation 52 (7.6%); code removed, no citation and truncated 0 each.

### Turn 72 — 2026-11-21 · Retrieval uses the rewritten question's embedding

**User:** "questions: for the retrievval we also used embedded rewritten query?"

**Agent actions:** Confirmed (`_select(p.standalone, ...)`): the resolver, BM25 (with glossary) and vector search all run on the rewritten question. On a first message there can be two embeddings: F2 on the original message and retrieval on the rewrite. The second is a cache hit if the text is unchanged, otherwise a second call (82% of run 1's questions were rewritten). On follow-ups there is one embedding, and the floor reuses its score after retrieval. Suggested a separate "embed rewritten question (cached if unchanged)" step inside the retrieval box.

### Turn 73 — 2026-11-21 · Back to the post-check: diagram form

**User:** "ok bakc to the post generation test"

**Agent actions:** Gave F5 in diagram form. Its inputs are the full answer and the retrieved excerpt labels. Its four checks lead to the cleaned answer, badges and cited sources, and then the turn is saved to SQLite. It has no reject exit and no retry, and runs at the end of streaming, after which the browser swaps in the cleaned text. Listed three weaknesses: it checks form, not truth; 7.6% of run 1 answers were shown with an invalid-citation badge; and the eval's citation check was stricter than the app's (the open checker fix). Asked which part to look at more closely.

### Turn 74 — 2026-11-21 · Post-check in one line each

**User:** "yes so shortly what exatcly do we check there?"

**Agent actions:** Short list of the four code checks: code blocks removed; each citation checked against the excerpts sent; no citation at all; truncation at the length limit. Flags only, no blocking or regeneration.

### Turn 75 — 2026-11-21 · Review of the user's full scheme

**User:** "added the full scheme to the scheme folder, can you check it? 1) orpfography and grammar check 2) correctness 3) crucial detail was missed" (`scheme/Untitled Diagram.drawio.png`)

**Agent actions:** Checked the drawing against the code. Also looked up the rate limiter (`app/api.py`, `app/guards/ratelimit.py`, `app/config.py`), which the drawing does not show.
- Spelling and wording: "retruns" → "returns a"; "=>0.64" → "≥ 0.64"; "is code?" → "code request?"; "Post-generation test" → "check"; "citations?" → "valid citations?"; mark the clarification as model-written.
- Correctness: the overall flow, F1-F3 exits, top_k = 8, history to generation and logging are right. Retrieval is hybrid, not embeddings only. F1 also rejects empty messages. Refusals and clarifications are logged too.
- Crucial missing details:
  1. history also goes to the guard, which needs it to rewrite follow-ups;
  2. F2 runs first only on the first message; follow-ups are checked after retrieval;
  3. the post-check needs the excerpt labels from retrieval;
  4. a rate-limit step before F1 (8 per minute and 100 per day per IP, 1,500 per day in total, 30 turns per session);
  5. the generation inputs: system rules, answer style, up to 3 carried-over excerpts;
  6. the model names `gemini-3.8-flash` and `gemini-embedding-2`.
- Optional: guard fail-open, embedding fallback to BM25 with the floor skipped, and streaming before the post-check.

### Turn 76 — 2026-11-21 · References and BM25 explained

**User:** "so apart form the comparison between embedded reqritten query and ai acts embeddings we also need to show refernces and BM25? explain erferences and BM25?"

**Agent actions:** Explained the three search methods, which run side by side on the rewritten question, from `app/retrieval/search.py`:
- the reference resolver (regex for articles, annexes, recitals and defined terms; an exact reference is forced first, a passing mention gets a boost);
- BM25 keyword search (rare words weigh more; the lay-to-legal glossary expands the query for BM25 only);
- embeddings (meaning).
- They are merged with Reciprocal Rank Fusion (K = 60; dense 1.0, BM25 0.25 from E4; recitals ×0.8), then the top 8 are kept.
- Cited E1's measured gains (top-5 hit rate 66% → 78% → 82% → 94%) and suggested drawing three parallel branches into an RRF merge box.

### Turn 77 — 2026-11-21 · Excerpt labels, rate limits and carried-over excerpts in detail

**User:** asked to elaborate on the excerpt-label arrow into the post-check; on point 4 (rate limits), "why we have this limitation and how the chekc is being condicted?"; and on "up to 3 excerpts carried over from the previous answer on follow-ups".

**Agent actions:** Explained from the code (`citations.py`, `app/guards/ratelimit.py`, `api.py`, `pipeline.stream` / `_select`):
- Labels: they are made at chunking, carried with each excerpt into the prompt, and the post-check validates every bracketed citation against the list sent (a narrower sub-point is valid). An invalid citation shows the model cited from memory.
- Rate limits: in-memory counters checked in `api.py` before the pipeline, keyed by IP (first `X-Forwarded-For` value). Order: global 1,500/day, then 100/day per IP, then 8/minute per IP, each with a fixed reply; plus a 30-turn session cap counted in SQLite. Reasons: API budget on a public demo, abuse, and the cost of long sessions. Limitations stated: counters reset on restart, the IP header can be spoofed (the global cap is the backstop), and IPs are held in memory for up to a day.
- Carry-over: the first 3 validly cited chunk IDs of the previous answer are read from SQLite and added to the new top 8 within the 3,000-word budget. This keeps follow-ups like "what are the exceptions?" grounded in the earlier provision; run 1 had 8-11 excerpts per answer.

### Turn 78 — 2026-11-21 · Drawing labels and rate limits; checks run per message

**User:** "labels - i frankly do not kno how to rrepresent it in the system... budhed protection fine - lets introduce it but what shape shall i use? and this check runs like constantly is not it?"

**Agent actions:**
- Labels: suggested one data object (draw.io "Document" shape) between retrieval and generation: "8 excerpts, text + label". A solid arrow goes to the generation model (full text) and a dashed arrow to the post-check (labels only, as allowed citations); the carried-over excerpts from SQLite feed the same object.
- Rate limits: a rectangle "F0: rate limits" before F1, with the same red rejection arrow and its four limits listed, plus an optional dashed cylinder for the in-memory counters.
- Explained that no check runs continuously: everything runs once per incoming message. The limiter drops old timestamps and resets the day on the first message after midnight; no background timer.

### Turn 79 — 2026-11-21 · Hybrid retrieval recap

**User:** "oh hold on i forgot on the hybris retrieval, lets finish wit thta fist: BM25 and what else was there?"

**Agent actions:** Short recap of the three methods: the reference resolver (exact reference forced first), BM25 with the glossary (weight 0.25), and embeddings (weight 1.0). They are merged by RRF with recitals ×0.8, and the top 8 are kept. Gave a three-branch sketch for the diagram.

### Turn 80 — 2026-11-21 · Okapi BM25

**User:** "okapi bm25?"

**Agent actions:** Confirmed from the code and the installed library: `rank_bm25.BM25Okapi` with defaults k1 = 1.5, b = 0.75 (epsilon 0.25), built over the 893 chunks' tokenized text. Explained the name and the three ideas behind the score: rare words weigh more, repeated words give diminishing returns, and long chunks are lightly penalised.

### Turn 81 — 2026-11-21 · Wording of the three retrieval methods

**User:** proposed one-line descriptions (embeddings: rewritten embedded query against embedded chunks; Okapi BM25: ranking function; resolver: exact lookup in named parts of the Act) and asked whether they are correct.

**Agent actions:** Confirmed the idea and suggested sharper wording:
- embeddings: cosine similarity between the embedded rewritten query and the embedded chunks;
- BM25: keyword ranking on shared words, query plus glossary, rare words weighted more (every method ranks; the word basis is what distinguishes it);
- resolver: exact lookup of parts of the Act named in the query;
- plus one line for the RRF merge to the top 8.

### Turn 82 — 2026-11-21 · F0 traffic check, ready to draw

**User:** "ok now lest go vakc to the traffic user check"

**Agent actions:** Gave F0 ready to draw. It sits first, before F1, as a rectangle with a red rejection arrow. Its four limits are checked in code order, each with its exact fixed reply:
1. global 1,500 per day;
2. 100 per day per IP;
3. 8 per minute per IP (all three in `api.py`, in-memory counters);
4. 30 turns per session (at the start of `pipeline.stream`, counted in SQLite).

Included an ASCII sketch. Reminded that it runs once per message and counts every message, refused ones included.

### Turn 83 — 2026-11-21 · Scheme tab; request path removed from Source code

**User:** "located HTML file of the diagram in the scheme folder. add it to the sepearate tab in the Menu called 'Scheme'. then maybe lets remove the reuqets path form the Source code section. now i will review the Agentic usage gorupd of the tabs"

**Agent actions:**
- Inspected `scheme/embed.html` before serving it: one `<img>` tag with the diagram as a PNG data URI and an `onclick` handler that would open diagrams.net and post the diagram there. No other scripts.
- New endpoint `/api/scheme` (`app/api.py`): reads `scheme/embed.html` on each request and returns only the PNG data URI and the file's update time. The export's onclick is never used, so the tab updates automatically when the user re-exports.
- New "Scheme" tab in the menu (between Chat and Source code): a short description and the diagram on a white panel (legible in dark mode), with an "Actual size / Fit to width" toggle.
- Removed the "Request path" card from Source code and pointed its description to the Scheme page.
- Checked: ruff and 90 tests pass; in the browser the diagram renders (natural width 1,310 px), the toggle works, and Source code shows only "Files".

### Turn 84 — 2026-11-21 · Eval methodology section; browser caching fixed

**User:** "1) remove the lin The full evaluation log … in Evaluation. add there small section Eval methodology. describe that Gemnin no reasonin was sleected primarily becasue of teh latency, humanassessment (100 samples) assessed gemini with reasoninn, gemini no reasoning and mistarl using blind annotation and assessed all quite high. yet ewas leaning mroe towards mistral model. tested also brifly raw user query an dte rewirettien one. rewrting was seleceted even those the small test came out equal. why: to increase the quality of the responce and leave no roon for the unclear questions to the model."

**Agent actions:**
- The pointer line had already been removed in Turn 53. Confirmed it is absent from the code and from what the server sends; the user was seeing a cached page. This was the third time stale caching caused confusion, so `app/api.py` now sends `Cache-Control: no-cache` for the page and `/static/` files. Browsers revalidate on each load (304 when unchanged). Verified with a header check.
- New "Eval methodology" block at the top of the Evaluation page, after the summary cards, with four points:
  1. the three evaluation layers;
  2. Gemini without reasoning chosen mainly for latency (judge 9.09-9.13 for all three; TTFT 1.8 s vs 6.3-6.8 s; about half the cost of Gemini with reasoning);
  3. the blind human review (100 dev cases, A/B/C shuffled, all high at 8.8-9.1, leaning to Mistral 45 vs 27, not significant; weak judge-human agreement, so the judge catches failures rather than ranking);
  4. raw vs rewritten query (top-8 hit rate 94.7% vs 95.4%), with the rewrite kept to turn follow-ups and unclear wording into complete questions in the Act's terms.
- Numbers taken from the result files. Checked in the browser; 90 tests and ruff pass.

### Turn 85 — 2026-11-21 · Condensed conversation log; evaluation tiles

**User:** asked whether the Evaluation page's summary tiles miss key data points, and asked to restructure the log: "i dont wanna keep all teh messages, moreove it is super long … we gonna keep my actual messages only where it really matter and change smth for the project … Turns X-Y: evaluation … Decions 1. Summay of promot -> extend to se ethe full", with numbered build steps, a "what did i bring to the table" block, and three limitations (failed post-checks go nowhere; multilingual over budget; doubts about a separate LLM guard, kept for rewriting because of pertinence).

**Agent actions:**
- Moved the full log unchanged to `docs/CONVERSATION_LOG_FULL.md` (this file), so nothing is lost.
- Rewrote `docs/CONVERSATION_LOG.md` (18,000 → 3,500 words): key prompt; 9 numbered build steps; a two-column "who brought what" table; the log grouped by turn ranges with 20 key decisions, the user's prompts in short and the full prompts in expandable `<details>` blocks; the user's three limitations; the validation section (renumbered, updated with the human review and Mistral's reasoning).
- Enabled the `md_in_html` Markdown extension (`app/docs.py`) so expandable blocks render with their content formatted; checked in the browser (8 expandable prompts).
- Proposed additional evaluation tiles (answer to the first question) for the user to choose.

### Turn 86 — 2026-11-21 · Agentic usage shows only the conversation log

**User:** "in the table who brought what rename The user to Olesia then lets remove the Plan and Methodlofy tabs. and keep the converstaion log underthe AGnetic Usage only. then I think we will eb ready for the deployment"

**Agent actions:**
- Renamed the table column to "Olesia".
- Removed the Methodology and Plan sub-tabs; the server now serves only the conversation log (`DOCS` in `app/api.py`; other documents return 404). The files stay in the repository. 90 tests pass; checked over HTTP.
- Checked deployment readiness: no Dockerfile and no git repository yet; `.gitignore` already excludes `.env` and keeps the Gemini embedding cache. Listed what deployment to Railway needs.

### Turn 87 — 2026-11-21 · Agentic usage as one menu item

**User:** "no we have a Agentic Usage haveing only one page called 'Conversation log'. - does not make sense. rename Conversation log to Agnetic Usage and put it on the first level in the menu"

**Agent actions:** Removed the sub-menu (chevron, sub-tab list, its click handler and CSS); "Agentic usage" is now a first-level menu item that opens the log directly. Updated the page description, and shortened the document's own title to "How this project was built with an AI agent" so it does not repeat the page header. 90 tests pass; checked in the browser.

### Turn 88 — 2026-11-21 · Limitation: no learning from user feedback

**User:** "also add to the projetc limitations that there is no mechanism to imrpove the system based on teh user's feedback."

**Agent actions:** Added limitation 4 to `docs/CONVERSATION_LOG.md`: users cannot rate answers or report problems, nothing feeds back into prompts, retrieval or the evaluation set, and quality is known only from offline evaluations; the feedback box and ratings were proposed but not built (PLAN §8, item 3). Updated `docs/METHODOLOGY.md` §12 to match, and replaced two stale bullets there: "no end-to-end numbers yet" became the single-run and judge-noise caveat, and "Mistral not implemented" became "evaluated but not used in the app". Also added the post-check and multilingual limitations there.

### Turn 89 — 2026-11-21 · Is an old conversation kept after "New conversation"?

**User:** "okay, so if user presses on new conversation - their old converesation is being stored still?"

**Agent actions:** Checked `app.js` (the button handler) and `memory.py` / `api.py`: yes. The button only removes the session ID from the browser's localStorage and reloads; the old session's messages stay in SQLite indefinitely. There is no delete function or endpoint; only a redeploy on Railway (ephemeral disk) wipes them. Session IDs are random UUIDs, so others cannot read them without the ID. Proposed two small changes (not built): delete on "New conversation" via `DELETE /api/session/{id}`, and automatic deletion of sessions idle for more than 24 hours, which would make a truthful retention notice possible.

### Turn 90 — 2026-11-21 · No accounts: is a conversation still linkable to a person?

**User:** "ye but since we dont have an authentification, we cnanot link it to the specific user, is not it right?"

**Agent actions:** Confirmed that no login means no name or email, but checked two other links:
- The content of a conversation can itself identify someone.
- The server access log records the client IP next to `GET /api/session/<session id>` when a page restores a conversation (real line from the local log); on Railway its HTTP logs record visitor IPs with paths. So the data is pseudonymous, which under the GDPR is still personal data, not anonymous.

Proposed, not built: delete on "New conversation", deletion after 24 hours idle, moving the session ID from the URL into a header (or not logging that path), and a short notice asking users not to include personal details.

### Turn 91 — 2026-11-21 · Tooltip on "New conversation"; CSV export

**User:** "i guess lets not overdue it. yet lets add an info cloudfor user when they hover over the new conversation button - and state that it woudl clear their current conversations. maybe then we cna have some experrt button for the user to be able to export their conevrsation lie in the csv format?"

**Agent actions:**
- Server-side deletion not built (the user's choice).
- "New conversation" tooltip, worded to stay true (the server keeps the old session): "Starts a new conversation and clears the current one from this page. It cannot be reopened here, so export it first if you want to keep it."
- New "Export CSV" button with its own tooltip, disabled until a conversation exists. It builds the file in the browser from `/api/session/{id}`, with no server change. Columns: no, role (you / assistant), message, interpreted_as (the guard's rewrite, when different), type, style (Legal detail / Explanatory), cited_provisions (labels, de-duplicated). UTF-8 with BOM, named `ai-act-conversation-<date>.csv`.
- Tested in the browser without saving a file (the download was intercepted). This found and fixed two issues: the style showed the internal key "plain", and labels repeated when several chunks share one label. The tooltip appears on hover; 90 tests pass.

### Turn 92 — 2026-11-21 · Fixing the output check

**User:** "The output check does nothing when it fails. About 7% of answers had at least one invalid citation … lets maybe fix this point as well. and then start the deploment on the Railway"

**Agent actions:**
- Diagnosed before fixing: of run 1's 52 flagged answers, nearly all citations were valid forms the checker misread. Examples: comma-joined labels ("Art. 68(2), Art. 68(2)(a)"), shorthand lists ("Art. 53(1)(b), (b)(i)"), a point of a whole annex ("Annex VI, points 1–4"), a point inside a sent range, lettered and dotted points, sub-point ranges, a paragraph whose points were sent, and "/" separators.
- Extended `app/chat/citations.py` to read these forms, with two guards found by tests: a lead-in chunk such as "Annex III" (18 words, points in separate chunks) does not validate its points, and the parent-paragraph rule applies only to the citation as written (otherwise "Art. 26(8)" passed when "Art. 26(7)" was sent). 8 new citation tests and 1 pipeline test; 98 pass.
- Re-checked the saved answers (no API calls): answers with an unverified citation fell from 52 (7.6%) to 3 (0.4%) in run 1, from 24 to 0 (Gemini with reasoning), 11 to 0 (Mistral) and 63 to 3 (Explanatory). Two of run 1's three are genuine (Art. 34(4), Art. 60(5) not sent).
- The browser used its own, simpler check and would have shown the fixed forms in red. The server now sends a verdict per bracket (`brackets`, also saved with the answer, so reloads match), and the browser draws it: valid citations as links, unverified ones in red with "Not among the provisions this answer was based on: check it on EUR-Lex before relying on it". During streaming, unknown forms stay neutral. Checked with one real question (15 citations, all valid) and in the browser.
- Not built: regenerating the answer (rare now, and it would replace text the user is already reading). Limitation 1 and METHODOLOGY §12 updated.

### Turn 93 — 2026-11-21 · Deployment preparation (Railway)

**Agent actions (continuing Turn 92's "start the deploment on the Railway"):**
- Checked Railway's documentation (Public Networking > Specs & Limits; Fixing Common Errors). The edge proxy sets `X-Real-IP` for the client address, and X-Forwarded-For is not documented. The app must bind `0.0.0.0` on the injected `PORT`. The rate-limit key (`app/api.py`) now prefers `X-Real-IP`, then X-Forwarded-For, then the socket address. Whether a client-sent `X-Real-IP` is overwritten is not documented, so the global daily cap remains the backstop.
- Added `Dockerfile` (python:3.12-slim, uv 0.12.5 pinned, `uv sync --frozen --no-dev`, non-root user, uvicorn on `$PORT`) and `.dockerignore`. The image excludes `.env`, SQLite files, raw sources, unused embedding caches, per-case CSVs and the human review sheets.
- Built and ran the image with only `GEMINI_API_KEY` and `PORT=8091`. Health check, page, info, evaluation, scheme, log and static endpoints returned 200, and one real question was answered with no issues. Confirmed no `.env` in the image. Removed the test container and the temporary key file.
- Scanned the project (outside `.env`) for API keys: none. Image size 1.67 GB, mostly the unused local-embedding dependency.
- Waiting for the user's decisions on the GitHub repository (name, visibility) and the Railway set-up.

### Turn 94 — 2026-11-21 · External critique: production document missing

**User:** shared a critique from another session acting as a reviewer. It proposes a `docs/PRODUCTION.md` (executive summary, feasibility with evidence, cost model, risk register, prototype vs production design, effort by phase, proven vs not proven), a target-architecture draw.io page, one-hop cross-reference expansion with multi-provision questions, fixing stale docs, and cleaning the handover package (score "72 → ~90").

**Agent actions:**
- Verified its numbers against the results:
  - facts: 615 of 625 answers (it said 628);
  - false refusals: 17 of 658 in-scope questions, 2.6%, all by the guard (it said 0.5%);
  - cost: $0.0025 per answered question (it said $0.002-0.003);
  - invalid citations: 0.4% after Turn 92 (it said 7%);
  - "Mistral as a fallback" is overstated: it is a provider, not an automatic fallback.
- Confirmed the main gap: `docs/PRODUCTION.md`, promised in PLAN for the assignment's "feasibility, target design and effort estimation", does not exist; neither does `DECISION.md`, still referenced by PLAN, EVALUATION_LOG and dead API code. `architecture.html` dates from 2026-11-19.
- Recommended order: PRODUCTION.md first, then stale docs, then cleanup, then the user's target diagram page; cross-reference expansion deferred to the pilot plan unless time allows; then deploy.

### Turn 95 — 2026-11-21 · Removing sentences with bad citations? Repository on GitHub

**User:** "i actually dont know meyb in case we have invalid citation, we just remove the sentence form the responce? ok so lets do then the repo on the github, we also need gitignore file to ignore .env"; then chose a public repository named `AI_Act_HybridRAG`.

**Agent actions:**
- Checked the two genuine unverified citations in run 1 before answering. Both statements are correct with a wrong article number: "five years from the termination date of the subcontracting" cited as Art. 34(4), which does not exist (the source, Art. 33(4), was sent); and the notification of suspension or termination cited as Art. 60(5) (the source, Art. 60(8), was sent). Removing the sentence would delete correct information, so the in-place red warning was kept.
- Before the first push:
  - removed the dead `DECISION.md` reader from `/api/evals` (and its unused import);
  - wrote `evals/results/DECISION.md` (generation model, answer style, query rewriting, with numbers), which PLAN and EVALUATION_LOG refer to;
  - marked `docs/architecture.html` as the first version, pointing to the Scheme page;
  - added `/*.png` to `.gitignore` for the stray root screenshot.

  `.gitignore` already excluded `.env`, `.venv`, SQLite files and unused embedding caches; verified with `git check-ignore`. 98 tests pass.
- Initialised git (`main`), dry-ran the add (119 files, 27 MB, no `.env`), committed with the user's configured identity, and created and pushed the public repository with the user's `gh` login: https://github.com/tsiarletska/AI_Act_HybridRAG. Confirmed through the GitHub API that `.env` is absent.

### Turn 96 — 2026-11-21 · Methodology review; open items for 2026-11-22

**User:** "read the methodlofy file is there is"; then "ok so we have finished on the production file" and "log tomorrow we need to find favicon".

**Agent actions:**
- Read `docs/METHODOLOGY.md` and listed its stale parts: the status line, E9 "to be re-run", the model-selection section still marked planned, 90 tests (now 98), the timeline stopping at Turn 18, and the deployment and repository not mentioned. Not fixed yet.
- Found no `PRODUCTION.md` in the repository, although the user considers it finished. To be checked.

**To do on 2026-11-22:**
- Find a favicon for the web app. `app/web/` has none at the moment.

### Turn 97 — 2026-11-22 · Effort to finish; production document written

**User:** asked how many hours remain to finish the development plan (feasibility) and deploy on Railway; then pasted an external reviewer's outline for `docs/PRODUCTION.md` (summary, feasibility with evidence, cost model, risks, target design, effort, proven vs not proven).

**Agent actions:**
- Estimated 5–7 hours: Railway deploy and live check 1.5–2 h, production document 2.5–3.5 h, methodology update 0.5–1 h, README 0.5 h, favicon 0.25 h.
- Wrote `docs/PRODUCTION.md` on the reviewer's structure, with figures recomputed from run 1 instead of the reviewer's illustrations: facts found 615/628, false refusals 3/628, 266/276 unwanted requests stopped, 0 injections obeyed, time to first word 3.3 s median (1.8 s is the answer model alone), $0.0026 per answer. The reviewer's "7% invalid citations" was replaced by the current 0.4%. Cost model: ~$40 / ~$800 a month at 500 / 10,000 questions a day (today's prices, +30% margin), ~$75 / ~$1,500 from January 2027. Effort figures are marked as estimates: ~17 weeks, ~40 person-weeks, internal pilot after ~7 weeks.

### Turn 98 — 2026-11-22 · Gemini price check; Scalability section proposed; new evaluation tiles

**User:** asked whether Gemini 3.8 Flash prices rise in January; asked for the local site link and what a new "Scalability" section could contain (authentication instead of traffic limits, model cost per traffic tier, Railway hosting cost, multilingual); then asked to replace the four evaluation tiles (two were retrieval) with: chunking accuracy on dev, LLM-judge overall for the selected model, TTFT median for the selected model, retrieval ablation recall.

**Agent actions:**
- Re-read the Gemini pricing page: 3.8 Flash goes from $0.75 / $3.75 to $1.50 / $7.50 per 1M tokens on 1 Jan 2027, as in `app/pricing.yaml`; no change announced for the guard model or the embedder.
- Started the app locally (http://127.0.0.1:7860). Proposed the Scalability content: limits become per-user quotas (the global cap stays), what breaks first (SQLite, in-process rate limiter, in-memory index), provider quotas, load test, caching, corpus growth, multilingual cost, EU region, retention. Railway prices still to be fetched.
- Evaluation tiles (`app/web/app.js`), all read from `/api/evals`: chunking recall at 500 words on dev 0.94 (alternatives 0.42–0.90); retrieval ablation recall@5 on dev 0.94 (BM25 alone 0.66); judge overall 9.12 for `gemini-3.8-flash`; TTFT median 1.8 s for the generation model, with 3.3 s including guard and retrieval in the subtitle.

### Turn 99 — 2026-11-22 · Railway prices; Scalability section

**User:** "yes, fetch railway prices and write the scalability section"; caching repeated questions as a further development idea; multilingual as further development, without a cost estimate; authentication as further development (own history), not a traffic measure; Scalability as its own section.

**Agent actions:**
- Read railway.com/pricing and the Railway docs (plans, regions) on 2026-11-22: memory $10 per GB-month, CPU $20 per vCPU-month, volumes $0.15 per GB-month, egress $0.05 per GB, per-second billing; Hobby $5 and Pro $20 a month including the same amount of usage; Pro up to 42 replicas; one EU region, EU West (Amsterdam).
- Added `docs/PRODUCTION.md` §4 Scalability: running cost by traffic (pilot 500/day, production 10,000/day, large 100,000/day; model cost today and from January 2027; Railway set-up and estimated monthly cost, from the measured 105 MB memory and 1 KB answer / 65 KB page); what changes as traffic grows (SQLite → Postgres, in-process rate limiter → Redis, global cap of 1,500/day to raise, provider quota, EU region, retention); further development ideas (answer cache, user accounts with own history, multilingual). The cost model moved there from §1; Effort became §5, proven/not proven §6.
- Removed authentication from the effort phases, the target-design table, the diagram and the abuse mitigation, and multilingual from the effort doublers, as both are further development.

### Turn 100 — 2026-11-22 · Production page on the site

**User:** "hmm but i dont see a nerw section on the web site".

**Agent actions:** added a **Production** tab between Evaluation and Agentic usage that renders `docs/PRODUCTION.md` (all six sections, Scalability as §4) through the existing `/api/docs/{name}` endpoint (`app/api.py` `DOCS`, `app/web/index.html`, `app/web/app.js`). Restarted the local server; the endpoint returns all section headings; 98 tests pass.

### Turn 101 — 2026-11-22 · Production page trimmed

**User:** after checking the Production tab: remove the "From prototype to production" opening (title, introduction, summary); risks as a list without likelihood and impact, with a short mitigation for the first risk; remove Target design; keep Scalability, with "what has to change as traffic grows" as a short list (app container, database, traffic limit per user, stored conversations) and the further development ideas; remove the Effort estimate and "What the prototype proved and what it did not".

**Agent actions:** rewrote `docs/PRODUCTION.md` to three sections (1 Feasibility, 2 Risks and mitigations, 3 Scalability), renumbered cross-references, moved the run-1 provenance note under the feasibility table, and updated the Production tab description and the METHODOLOGY records table.

### Turn 102 — 2026-11-22 · Favicon; repository update

**User:** "lets add some favicon. what dimenstions shall i think about here? and then we need to update repo on the GitHUB".

**Agent actions:**
- Made the favicon from the § mark the sidebar already uses (dark rounded square, white §): `app/web/favicon.svg` (scales to any size), `favicon.ico` with 16, 32 and 48 px for older browsers and bookmarks, and a 180 px `apple-touch-icon.png` for iOS home screens. Linked them in `index.html` and served `/favicon.ico` at the site root (`app/api.py`). 98 tests pass.
- Committed the day's work (production page, evaluation tiles, favicon, documentation fixes) and pushed it to `main`.

### Turn 103 — 2026-11-22 · Deployment on Railway

**User:** created the Railway project and asked whether a separate backend, frontend and SQLite were needed; then reported a crash after the first deploy, added the key, generated the domain, and sent the URL: https://aiacthybridrag-production.up.railway.app.

**Agent actions:**
- Explained that one service is enough: FastAPI serves both the API and the web page, and SQLite is a file inside the container. A volume is optional, and must be mounted at `/data` with `DB_PATH=/data/app.sqlite3`, never at `/app/data`, where the chunks and embeddings live.
- The crash came from the missing `GEMINI_API_KEY` (the embedding client is created at start-up). Advised setting `PORT=8080` as a variable and as the domain's target port.
- Found and fixed `.dockerignore` excluding all PNG files, which kept the new Apple touch icon out of the image (commit `a45d2a7`).
- Checked the live site: all pages and API endpoints return 200 in about 0.25 s; a fines question answered correctly with [Art. 99(3)] and [Art. 100(2)]; first words after 2.8–3.7 s (3.3 s median locally); weather refused in 0.55 s. Rate limit: after more than 8 requests within a minute (code requests, which the pre-filter refuses at no API cost), further requests were refused with `rate_limit`; requests with a forged `X-Real-IP` / `X-Forwarded-For` were still refused, so Railway sets `X-Real-IP` itself and the limit counts per visitor. Updated the METHODOLOGY limitation.

### Turn 104 — 2026-11-22 · Contact and repository link in the sidebar

**User:** asked to add their email under the regulation block in the sidebar, and a link to the GitHub repository with the text "GitHub repo", then push so they can redeploy on Railway.

**Agent actions:** added both links under "Original text, OJ 12.7.2024" (`app/web/index.html`, `.side-doc-links` in `styles.css`; muted, underlined, wrapping on narrow screens), committed and pushed to `main`.

---

## How the output was validated

AI-generated code was not accepted on trust. Every step was checked against the source document or a deterministic test:

1. **Facts from the source, not from memory.** Gold answers and gold chunk IDs come from phrase searches over the parsed text, for example fines in Art. 99(3)–(5) and dates in Art. 113. The model's recollection of the Act was never used as ground truth.
2. **Unit tests (`tests/`, 90 tests).**
   - Counts: 113 articles, 180 recitals, 13 annexes, 68 definitions.
   - Every article/recital/annex has at least one chunk, and no article text is lost (every word of every paragraph appears in its chunks).
   - Labels and anchor URLs, the superscript `10^25` preserved, bounded chunk sizes, cross-reference extraction (including ignoring references to other acts), and the resolver on exact vs passing references.
3. **Fail loudly.** Silent "auto-fixes" were replaced by errors. Making duplicate IDs raise exposed the Articles 102–110 parser bug, which a passing-but-lenient test had hidden.
4. **Ablation instead of a single number.** Each retrieval component was added in turn and measured. The article-title ranker was tested and **rejected** because it gave no gain.
5. **Dev/test split.** Retrieval was tuned on a 50-question dev set. A 25-question test set was written before any tuning.
   - **Caveat:** the test set was viewed three times, and one resolver change (recognising "counts as") was made after test misses had been printed. It is now frozen.
   - Final numbers:

| Retrieval (recall@5 / MRR@8) | BM25 | Dense | Hybrid | + glossary | **Product** (+ resolver) |
|---|---|---|---|---|---|
| Dev (50) | 0.66 / 0.49 | 0.66 / 0.54 | 0.78 / 0.67 | 0.82 / 0.70 | **0.94 / 0.82** |
| Test (25), before tuning | 0.84 / 0.64 | 0.80 / 0.65 | 0.80 / 0.73 | – | 0.84 / 0.75 |
| Test (25), final | 0.84 / 0.64 | 0.80 / 0.65 | 0.80 / 0.73 | 0.80 / 0.73 | **0.88 / 0.81** |

6. **Thresholds are calibrated, not guessed.** The relevance floor blocks 13/15 clearly off-topic queries and 0/50 in-scope ones. It is set per embedder by one rule: gemini2 0.64, local 0.60 (`evals/results/relevance_floor_<embedder>.json`).
   - The BM25 fusion weight was tuned on dev only (`evals/results/bm25_weight_sweep.json`).
8. **Provider APIs were tested before being relied on.** The models were listed through the API rather than taken from memory. Smoke tests showed that `gemini-embedding-2` merges several texts in one request into a single vector and ignores `task_type`. The docs confirmed both, and the code wraps each text separately and uses the documented text prefixes.
9. **Embedder comparison on the same questions.** Recall@5 (dev / test): local 0.94 / 0.88, gemini-embedding-001 0.98 / 1.00, **gemini-embedding-2 0.98 / 1.00**, which has the best recall@1 and MRR on both. The test set was run once per embedder, after all choices were made on dev, with failures not printed.
   - The gemini2 relevance floor (0.64) was checked on the frozen test set as a count only: 0/25 blocked.
   - Caveat: the test set is now saturated (recall@5 = 1.00), so it can no longer tell later retrieval changes apart. A harder held-out set would be needed for that. The end-to-end eval (M5) has its own split.
10. **Chunking strategy chosen by measurement** (`docs/CHUNKING.md`). Seven strategies were run through the same pipeline and scored on strategy-agnostic gold (5-gram coverage) at fixed context budgets. The decision was made on dev and confirmed by one test run. Paragraph-level's losses were diagnosed per case on dev only.
11. **Built features checked in a real browser**, not only by tests. The check found four bugs that the unit tests had missed; they are listed in `docs/EVALUATION_LOG.md` (E6), each fixed with a test where possible.
7. **Independent review of the agent's work.** A second model reviewed the plan and the code at checkpoints. Its findings (the test-set leakage, the citation-format mismatch, silent renaming) are recorded above and were acted on.
