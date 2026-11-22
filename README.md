# AI Act Assistant

A question-answering assistant for the **EU Artificial Intelligence Act** (Regulation (EU) 2024/1689, original text, OJ 12.7.2024). Ask a question in plain English and get an answer grounded in the text of the Act, with every statement cited to the article, paragraph, annex or recital it comes from, linked to EUR-Lex.

**Repository:** https://github.com/tsiarletska/AI_Act_HybridRAG

## How it works

1. **Ingestion.** The Act's HTML is parsed into 893 chunks that follow its structure: one per article paragraph, definition, recital and annex point, each with a stable ID (`art_99_3`) and a citation label (`Art. 99(3)`).
2. **Guardrails, cheapest first.** Rate limits, then a regex pre-filter (code requests, injections), then an embedding relevance floor (clearly off-topic questions), then a small guard model. The guard rewrites follow-ups into standalone questions and asks back when a question is ambiguous.
3. **Hybrid retrieval.** A reference resolver (for "Article 6(2)", "Annex III", defined terms), BM25 and Gemini embeddings, combined with weighted rank fusion.
4. **Answer.** `gemini-3.8-flash` answers only from the retrieved excerpts and cites each statement in a fixed format. A post-check verifies every citation against the excerpts.
5. **Memory.** Conversations are kept in SQLite; the last turns and the previously cited provisions carry into follow-ups.

The web app has six tabs: **Chat** (with a Legal detail / Explanatory style toggle), **Scheme** (architecture diagram), **Source code**, **Evaluation**, **Production** (feasibility, risks, scalability and cost) and **Agentic usage** (how it was built with an AI coding agent).

## Results in brief

From the 1,000-case end-to-end evaluation of the selected setup (details in `docs/PRODUCTION.md` and `docs/METHODOLOGY.md`):

| | |
|---|---|
| Expected facts found | 615 of 628 answerable questions (98%) |
| Wrongly refused | 3 of 628 (0.5%) |
| Unwanted requests stopped (off-topic, code, injection) | 266 of 276 (96%); 0 injections obeyed |
| LLM judge (Claude Sonnet 5.5) / blind human review | 9.12 / 8.82 out of 10 |
| Time to first word, median | 3.3 s (answer model alone 1.8 s) |
| Cost per answered question | about $0.0026 |

## Run it locally

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env          # then put your Gemini API key in .env
uv run --env-file .env uvicorn app.api:app --port 7860
```

Open http://127.0.0.1:7860. Only `GEMINI_API_KEY` is needed to run the app. `MISTRAL_API_KEY` is needed only to run the Mistral comparison, and `ANTHROPIC_API_KEY` only for the LLM judge (`evals/judge_e2e.py`).

The processed chunks and their Gemini embeddings are in the repository, so the app starts without rebuilding anything.

With Docker:

```bash
docker build -t ai-act-assistant .
docker run -p 8000:8000 -e GEMINI_API_KEY=... ai-act-assistant
```

## Tests and evaluations

```bash
uv run pytest                                                          # 98 unit tests, no API calls
uv run --env-file .env python -m evals.run_retrieval_eval --embedder gemini2
uv run --env-file .env python -m evals.run_e2e --split dev --sample 20  # end-to-end, small sample
uv run --env-file .env python -m evals.judge_e2e evals/results/<run>.csv --batch
```

The full list of evaluation commands is in `docs/METHODOLOGY.md` §13. Results are written to `evals/results/`.

## Configuration

All settings are environment variables with defaults in `app/config.py`. The ones you are most likely to change:

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | none | Required |
| `ANSWER_MODEL` | `gemini-3.8-flash` | Answer model; a `mistral-…` name switches to Mistral |
| `RATE_PER_MINUTE` | 8 | Questions per minute per visitor (IP address) |
| `RATE_PER_DAY` | 100 | Questions per day per visitor |
| `GLOBAL_PER_DAY` | 1500 | Questions per day for all visitors together |
| `MAX_TURNS_PER_SESSION` | 30 | Turns per conversation |
| `MAX_INPUT_CHARS` | 2000 | Maximum message length |
| `DB_PATH` | `data/app.sqlite3` | Where conversations are stored |
| `PORT` | 8000 | Port the server listens on (Docker) |

Rate-limit counters are kept in memory, so they reset on restart. Refused requests do not count and cost nothing.

## Deployment (Railway)

One service from this GitHub repository; Railway builds the `Dockerfile` and redeploys on every push to `main`.

1. New project → Deploy from GitHub repo.
2. Variables: `GEMINI_API_KEY`, and `PORT=8080`.
3. Settings → Networking → Generate Domain, target port `8080`.

No separate frontend or database service is needed: FastAPI serves the web page, and SQLite is a file in the container. Without a volume, stored conversations are reset on each deploy. To keep them, mount a volume at `/data` (not `/app/data`, which holds the chunks and embeddings) and set `DB_PATH=/data/app.sqlite3`.

## Repository layout

```
app/
  ingest/      HTML parser and structural chunker
  retrieval/   reference resolver, BM25, embedders, fusion
  chat/        pipeline, prompts, citation checker, memory
  guards/      pre-filter, rate limiter
  llm/         Gemini and Mistral providers
  web/         HTML/CSS/JS front end
  api.py       FastAPI app
data/          the Act (HTML, PDF, SHA-256 hashes), chunks, embeddings
evals/         evaluation scripts, test cases, results
docs/          documentation (below)
scheme/        architecture diagram (draw.io export)
tests/         unit tests
```

## Documentation

| File | Contents |
|---|---|
| `docs/PRODUCTION.md` | Feasibility with measured evidence, risks and mitigations, scalability and running cost |
| `docs/METHODOLOGY.md` | How the system was designed, built, evaluated and validated |
| `docs/PLAN.md` | Original plan, architecture and model-selection strategy |
| `docs/EVALUATION_LOG.md` | Every evaluation run, with commands and numbers |
| `docs/CHUNKING.md` | Chunking strategy comparison |
| `evals/results/DECISION.md` | Model, answer style and query-rewriting decisions |
| `docs/CONVERSATION_LOG.md` | Key prompts and how the AI coding agent's output was validated (condensed) |
| `docs/CONVERSATION_LOG_FULL.md` | The full turn-by-turn log of the build |

## Limitations

- Answers use the **original 2024 text**; later amendments are not reflected. The app shows this in a banner and in answers about dates.
- Not legal advice.
- English only; multilingual answers are designed but not built.
- Questions that need several provisions combined were not specifically evaluated.

Contact: terletskaolesia@gmail.com
