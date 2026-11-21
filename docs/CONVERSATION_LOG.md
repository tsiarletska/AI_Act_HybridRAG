# How this project was built with an AI agent

This project was built together with an AI coding agent (Claude Code, model Claude Opus 5.5), from 17 to 21 November 2026, over 85 conversation turns. This page condenses that conversation: the steps of the build, who contributed what, the user's prompts that changed the project, and the known limitations. The complete turn-by-turn record is kept in `docs/CONVERSATION_LOG_FULL.md`.

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

## How the project was built

1. **Concept and plan** (Turns 1–3). Analysed the AI Act's HTML structure (113 articles, 180 recitals, 13 annexes), wrote the plan, and fixed the frame: one generation model chosen by evaluation between Gemini and Mistral, a cheap model as a guard, the original 2024 text as the corpus.
2. **Corpus, chunking and retrieval** (Turns 4–6). Parsed the Act into 893 structural chunks with citation labels and EUR-Lex links, built hybrid retrieval (reference resolver + BM25 + embeddings), chose `gemini-embedding-2` and the structural chunker by measurement (retrieval and chunking evaluations on a dev/test split).
3. **First working app** (Turn 7). Backend (guard, relevance floor, pre-filter, rate limits, citation check, SQLite memory, streaming) and a four-tab web interface, tested in the browser.
4. **Architecture and design ideas** (Turns 8–15). Drew the architecture, debated the guard's role, designed and tested a multilingual approach (later parked), added the answer style toggle.
5. **Evaluation set-up** (Turns 16–21). Generated a 1,000-case test set (700 dev / 300 test), built the end-to-end runner with per-step latency and the LLM judge (Claude Sonnet), ran a 13-case smoke test.
6. **Generation model comparison** (Turns 22–39). Three full runs graded by the judge: Gemini without reasoning, Mistral Large 4, Gemini with reasoning. Gemini without reasoning selected.
7. **Results on the Evaluation page** (Turns 40–42). Generation model table, LLM-as-judge charts, selected setups highlighted.
8. **Answer style test and human review** (Turns 43–52). Legal vs Explanatory on the same 1,000 cases; a blind human review of 100 answers per setup; disclaimer and screen-fit fixes.
9. **System walkthrough and hand-drawn scheme** (Turns 53–85). Step-by-step review of the request path against the code, the user's draw.io scheme validated, a raw vs rewritten query experiment, Scheme tab and evaluation methodology added.

---

## Who brought what

| Olesia | The agent |
|---|---|
| The three requirements: memory with clarifying questions, guardrails that protect tokens, a deterministic regex evaluation | Structural chunking along the Act's own legal anchors, and a method to compare chunking strategies fairly |
| Gemini vs Mistral as candidates, with one generation model chosen by evaluation | Hybrid retrieval: reference resolver + BM25 + embeddings, merged by rank fusion |
| A cheap model as a gate before the expensive one, with its latency and cost measured | Query rewriting inside the guard, so follow-ups become complete questions; citation carry-over between turns |
| LLM-as-judge with a Claude model (Sonnet) from a different family than the candidates | A fixed citation format, checked in code against the excerpts sent |
| `gemini-3.8-flash` over Flash-Lite for answers, from professional experience with multilingual work | A calibrated relevance floor (0.64) and fixed, model-free refusal texts |
| An equal comparison: a Gemini run with reasoning to match Mistral | Dev/test discipline: tune on dev, check once on a frozen test split |
| The 1,000-case design: deterministic + LLM + human layers, per-step latency, one CSV row per case | A paired style test and a style-aware judge, with both styles graded by the same prompt |
| A blind human review of 100 cases (A/B/C, no model names) | Checks of the providers' APIs before relying on them (embedding batching, Mistral's reasoning cannot be switched off) |
| The multilingual idea, using the Act's official translations | Statistics on small differences: sign tests, the judge's own run-to-run noise |
| Questioning the design: e.g. "we don't pass the original query at all?", which led to the raw vs rewritten query test | Measuring before answering, e.g. how often the guard rewrites (82%) and what the generation model actually receives |
| The answer style toggle, the disclaimer, the privacy idea, the Scheme tab and the hand-drawn system diagram | Fixes found by reviewing its own work: test-set leakage, silent renaming, stale caching, overstated write-ups |

---

## Log

Each group lists the turns it covers. Key decisions show the user's prompt in short; expand to read it in full.

### Turns 1–3 · Concept and plan

The agent analysed the document and wrote `docs/PLAN.md`; the user answered its questions on providers, interface, deployment and citations.

**Decision 1. Providers, interface, citations.** Gemini and Mistral; an HTML app with four sections (chat, source code, evaluation, agentic usage); links to articles and paragraphs as citations.

<details markdown="1">
<summary>Full prompt</summary>

> right, answer to your questions:
> 1) Gemini models and Mistral
> 2) HTML. structure: the interface itself, where user can ask the question, 2) the source code (engine on python) 3) evaluation results 4) agentic usage (here we would need to provide the key prompt and the plan that we would develop i order to completed the task). in oreder to provide the key prompt, create the .md file and log our convesration there.
> 3) would be nice to try Hugging Space, otherwise the GitHUb Action or Railway. would need to provide the link to the system
> 4) citations: i'd go with the links to the article and paragraphs only. not a strict requirement on it

</details>

**Decision 2. One generation model, chosen by evaluation; a cheap guard; the original text.** Gemini and Mistral are compared, not used together; the corpus is the original 2024 text, with a banner noting later amendments.

<details markdown="1">
<summary>Full prompt</summary>

> 1) we are not going to use mistral and gemini as answering models at the same time. we would do teh test of the evaluation - which one is showing better results. we would need to develope also the evauation startegy. and the result would be located on the dedicated for it page
> 2) i agree, we need a cheap model as a guidrail.
> 3) source: lets go with te original one.
> we are doing the task in te frames of the following instruction: *[the assignment: a natural language interface prototype for one EU regulation (the AI Act) from EUR-Lex; outputs: a solution architecture diagram and Python prototype code; AI coding assistants allowed if the key prompts and the validation of their output are shared]*

</details>

### Turns 4–7 · Corpus, chunking, retrieval, first app

Parser and 893 chunks; hybrid retrieval; retrieval evaluation (dev 50 / test 25); `gemini-embedding-2` chosen (recall@5 dev 0.98 / test 1.00); seven chunking strategies compared, structural kept; backend and interface built, 79 tests, browser-checked.

**Decision 3. Chunking and Gemini embeddings.**

<details markdown="1">
<summary>Full prompt</summary>

> i've addded the gemini first, mistral gonna come up bit later on.
> i suppose that even tho the document is small we shoudl still use chunking rather then fit it into the same context window.
> so for the embeddings I think we may use one of the gemini models as well for this process.

</details>

**Decision 4. Compare chunking strategies.** "lets assess various chunking stategies, what would be the best approach considering the nature of teh document" → seven strategies at fixed context budgets; structural chunking wins at tight budgets (`docs/CHUNKING.md`).

### Turns 8–15 · Architecture, guard, multilingual idea, answer style

**Decision 5. A cheap guard before the generation model, with its cost measured.**

<details markdown="1">
<summary>Full prompt</summary>

> So what I was thinking about first, let's draw the scheme overall, how the system would look like. So we have discussed that we're gonna use some cheap model to serve as guardrail and to understand the relevance of the user's questions to the topic in order to save some tokens for more strong model which gonna respond. And I want to also have it as a part of the evaluation process to check how much latency does it add to the system and how much overall cost. […]

</details>

**Decision 6. Multilingual design: one English index plus the official translations.** The Act exists in 24 aligned language versions; the user chose 5 (English, Lithuanian, Polish, Finnish, French). A retrieval experiment (E8) showed translate-then-search matches English. Parked later (see Limitations).

<details markdown="1">
<summary>Full prompt</summary>

> So there are a lot of languages this document have, like a different variation and translation, and it's kind of cool because there is like all the terminology is correct and revised. So I wanted to play about this idea a bit more, and if we to keep the third layer of LLM, which can identify the intent of the user, we can also use it for the language identification in order for the response would be in correct language. However, if we do so, how are we gonna deal with embeddings and the vector database? Do we need to create different indexes […]

> Okay, so I think we don't maybe need to keep all 24 languages, and we can maybe stop on 5 of them. But the idea for this infrastructure should be scalable […] English index plus align text. Yeah, actually. I think that's something that I originally have had in mind. […]

</details>

**Decision 7. An answer style toggle.** Legal detail / plain (later "Explanatory"); the style comes from the toggle, not from a model guess.

<details markdown="1">
<summary>Full prompt</summary>

> also in the inetrface i wanna add a toggle -to allow user to have formla or informal answer. cause you know it is a law it is heavy to read an dif user wanna have a simple answer to the simple quetsioni would like to rpovide it.

</details>

**Decision 8. The evaluation design: 1,000 cases, three layers, per-step latency.** Deterministic checks, an LLM judge and human scoring on the same data; injection, off-topic and quality cases; latency per step and per outcome; one CSV row per interaction.

<details markdown="1">
<summary>Full prompt (shortened)</summary>

> […] Then I want to elaborate a bit more on the test design and how the dataset would look like. So finally I want to perform three tests. […] it would contain like the data on, let's say, 1,000 interactions. […] And then I want to have the LLM check on the same 1,000 samples, like using the stronger model. I'm not sure yet whether it's going to be Gemini or Claude. […] And then for English part I want to have a human check, which I'm gonna do […] I want to have the samples where we're gonna have some injection test […] Then the same outcome I expect with the out of the topic guards. […] And then I want to also measure the latency on the each step […] So as an output, when we're gonna run this test, I want to have like the, I don't know, CSV file which I can analyze […]

</details>

**Decision 9. English only for the deadline.** "now lets stick to english and the tone. if i have more time on the weekend we do the multilanguage as well."

### Turns 16–21 · Evaluation set-up

1,000-case dataset generated and reviewed; runner with per-step timers; judge script; Pinecone judged unnecessary (893 vectors, 2.7 MB in memory); smoke run of 13 cases.

**Decision 10. Claude Sonnet as the judge, thinking off.** A different model family than both candidates (no self-preference, fair to Gemini and Mistral); five criteria plus an overall 0–10 score and a one-line reason.

**Decision 11. Why `gemini-3.8-flash` generates the answers.**

<details markdown="1">
<summary>Full prompt</summary>

> So I want to log the fact that we have selected Gemini 3.0 Flash above Gemini 3.5 Flash Lite based on the fact that we have been intending to build multilingual rack. So that is still an intention if we have enough time to work on it. For my job, we have seen that Gemini 3.8 is behaving better with the translation and being like in multilingual context in general compared to Gemini 3.5, while Gemini 3.5 is good with the summarization, rewriting, etc, etc. So solely based on this fact, this model was selected over another one.

</details>

### Turns 22–39 · Generation model comparison

Run 1 (Gemini, no reasoning), run 2 (Mistral Large 4), run 3 (Gemini with reasoning), each 1,000 cases graded by Sonnet. Mistral turned out to reason by default (it cannot be switched off), which made it 3–4× slower to the first word. Result: quality tied (judge 9.09–9.13); Gemini without reasoning kept for latency (1.8 s to the first token) and cost.

**Decision 12. An equal comparison with reasoning on both sides.** "can we run now gemini with reasoning on in parallel? i wann ahave the more or less equal comparisom" → run 3 at Gemini's `medium` level, the closest match to Mistral's minimum.

**Decision 13. No Opus agreement check.** "we not gonna do the opus check" → the user's own scores became the check on the judge.

### Turns 40–52 · Results page, answer style test, human review

Evaluation page: generation model table and six LLM-as-judge charts. Answer style: Explanatory scored lower than Legal detail (8.54 vs 9.00) and stayed dense; Legal detail kept as default. Blind review: the user scored all three setups high (8.8–9.1), leaning towards Mistral. Not-legal-advice disclaimer above the chat; chat fitted to the screen.

**Decision 14. Style test on the selected model only.** "yes that is rght lets do only gemeni 3.8 then" → the same 1,000 cases in both styles, graded by the same style-aware judge prompt.

**Decision 15. A blind human review of 100 cases.** "i plan to perfom the qualitative check of approximately 100 responces … include 100 intercations as well as answers of 3 models. we may do the blind assessment."

**Decision 16. A disclaimer above the chat.** "I think it would be worth adding some kinda of the disclaimer. above the chat: This is not legal advice, it is an AI-based chatbot. […]"

**Decision 17. Privacy idea logged, not built.** "i am keen on not to store the intercation anywhere" → recorded with the facts checked (PLAN §8, item 3).

### Turns 53–85 · System walkthrough, scheme, query rewriting

The user walked through the request path step by step (traffic limits, pre-filter, relevance floor, guard, hybrid retrieval, generation, post-check, memory), each answer checked against the code, and drew the system in draw.io; the agent validated the drawing (spelling, correctness, missing details). The Scheme tab and the Eval methodology section were added.

**Decision 18. Test raw vs rewritten query.** "so we dont pass the original query at all? and we use the cheap model to reframe the human request?" → experiment A on 395 dev questions: equal for retrieval (top-8 hit rate 94.7% vs 95.4%).

**Decision 19. Keep the rewrite.** "lets keep it this way now, we will explain more in the meth on it" → kept so that follow-ups and unclear wording reach the model as complete questions in the Act's terms.

**Decision 20. A condensed log.** "i dont wanna keep all teh messages, moreove it is super long" → this page: the build steps, who brought what, decisions with expandable prompts, limitations. The full record moved to `docs/CONVERSATION_LOG_FULL.md`.

**Decision 21. Fix the output check.** "lets maybe fix this point as well" → the citation checker now reads comma-joined, shorthand, range and sub-point forms (7.6% → 0.4% of answers flagged), and the browser draws the server's verdict per citation, so a genuine unverified citation is marked where it stands.

---

## Limitations

1. **A failed post-generation check does not regenerate the answer.** Most "invalid" citations turned out to be the checker misreading valid forms ("Art. 68(2), Art. 68(2)(a)", "Annex VI, points 1–4"); after fixing it, answers with an unverified citation fell from 7.6% to 0.4% of run 1's answers. The rare genuine cases (a provision the model was not given) are marked in red at the exact spot, with a warning to check them, but the answer is neither blocked nor regenerated.
2. **Multilingual was designed but not built.** The Act's official, aligned translations could give answers in the user's language with the correct legal terms. The design and a first retrieval experiment (E8) were done, but building and validating five languages went beyond the time and budget of this project.
3. **The LLM guard as a separate step was debated.** The user hesitated about a model call in front of every question; its strongest case was language identification for the multilingual version. It was kept for query rewriting, because people are often unclear about what they want and need (the concept of pertinence: the question asked is not always the information needed). The raw vs rewritten query test found no retrieval difference, so its value rests on follow-ups and clarity rather than measured retrieval gains.

4. **No way to learn from users.** There is no mechanism to improve the system from user feedback: users cannot rate an answer or report a problem, and nothing they do feeds back into the prompts, the retrieval or the evaluation set. Quality is known only from the offline evaluations. A feedback box and per-answer ratings were proposed but not built (PLAN §8, item 3).

Further limitations are listed in `docs/METHODOLOGY.md` §12.

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
7. **Provider APIs were tested before being relied on.** The models were listed through the API rather than taken from memory. Smoke tests showed that `gemini-embedding-2` merges several texts in one request into a single vector and ignores `task_type`, and that Mistral Large 4 cannot switch reasoning off. The code handles both.
8. **Embedder comparison on the same questions.** Recall@5 (dev / test): local 0.94 / 0.88, gemini-embedding-001 0.98 / 1.00, **gemini-embedding-2 0.98 / 1.00**, which has the best recall@1 and MRR on both. The test set was run once per embedder, after all choices were made on dev, with failures not printed.
   - The gemini2 relevance floor (0.64) was checked on the frozen test set as a count only: 0/25 blocked.
   - Caveat: the test set is now saturated (recall@5 = 1.00), so it can no longer tell later retrieval changes apart. The end-to-end evaluation has its own 300-case test split.
9. **Chunking strategy chosen by measurement** (`docs/CHUNKING.md`). Seven strategies were run through the same pipeline and scored on strategy-agnostic gold (5-gram coverage) at fixed context budgets. The decision was made on dev and confirmed by one test run.
10. **End-to-end results checked three ways.** Deterministic checks, the Sonnet judge and a blind human review of 100 cases. Where they disagreed (e.g. ambiguous questions answered conditionally), the cases were read and the disagreement explained rather than averaged away.
11. **Built features checked in a real browser**, not only by tests. The first check found four bugs that the unit tests had missed; they are listed in `docs/EVALUATION_LOG.md` (E6), each fixed with a test where possible.
12. **Independent review of the agent's work.** A second model reviewed the plan and the code at checkpoints. Its findings (the test-set leakage, the citation-format mismatch, silent renaming) were acted on.
