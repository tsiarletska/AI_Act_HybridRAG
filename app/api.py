"""FastAPI app: chat (SSE), source viewer, evaluation results, docs. Serves the static frontend.

run: uv run --env-file .env uvicorn app.api:app --port 7860
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.chat.memory import Memory
from app.chat.pipeline import ChatService
from app.config import CORPUS, settings
from app.docs import render_markdown
from app.guards.ratelimit import RateLimiter
from app.llm.base import make_llm, price
from app.retrieval.search import Retriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "web"

app = FastAPI(title="EU AI Act assistant", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """The page and its assets change often during development: make browsers revalidate them on every load
    (a 304 when unchanged) instead of showing a stale cached copy."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

retriever = Retriever()
memory = Memory(settings.db_path)
limiter = RateLimiter(settings.per_ip_per_minute, settings.per_ip_per_day, settings.global_per_day)
service = ChatService(retriever, make_llm(settings.answer_model), make_llm(settings.guard_model), memory, settings)

SID = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------- pages & info
@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/info")
def info():
    return {
        "corpus": CORPUS,
        "chunks": len(retriever.chunks),
        "models": {
            "answer": settings.answer_model, "answer_thinking": settings.answer_thinking,
            "guard": settings.guard_model, "guard_thinking": settings.guard_thinking,
            "embedder": retriever.embedder_name,
        },
        "prices_today": {m: price(m) for m in (settings.answer_model, settings.guard_model)},
        "relevance_floor": retriever.relevance_floor,
        "performance": (_load("model_selection.json") or {}).get("production"),
        "limits": {"max_input_chars": settings.max_input_chars, "per_minute": settings.per_ip_per_minute,
                   "per_day": settings.per_ip_per_day, "turns_per_session": settings.max_turns_per_session},
    }


# ---------------------------------------------------------------- chat
class ChatIn(BaseModel):
    session_id: str | None = None
    message: str
    style: Literal["legal", "plain"] = "legal"  # answer style toggle in the UI


def _client(req: Request) -> str:
    """Rate-limit key. Railway's edge proxy sets X-Real-IP to the client's address (docs.railway.com, Public
    Networking > Specs & Limits, read 2026-11-21); X-Forwarded-For is a fallback for other proxies. The docs do not
    say whether a client-sent header is overwritten, so the global daily cap remains the backstop."""
    real = req.headers.get("x-real-ip", "").strip()
    fwd = req.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return real or fwd or (req.client.host if req.client else "unknown")


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


@app.post("/api/session")
def new_session():
    return {"session_id": memory.new_session()}


@app.get("/api/session/{sid}")
def get_session(sid: str):
    if not SID.match(sid) or not memory.exists(sid):
        raise HTTPException(404, "unknown session")
    return {"session_id": sid, "messages": memory.history(sid, limit=200)}


@app.post("/api/chat")
def chat(body: ChatIn, req: Request):
    sid = body.session_id if body.session_id and SID.match(body.session_id) and memory.exists(body.session_id) \
        else memory.new_session()
    msg = body.message[: settings.max_input_chars + 1]  # the pre-filter reports "too long"
    blocked = limiter.check(_client(req))

    def events():
        yield _sse({"type": "session", "session_id": sid})
        if blocked:
            yield _sse({"type": "final", "kind": "refusal", "text": blocked, "stage": "rate_limit"})
            return
        for ev in service.stream(sid, msg, body.style):
            yield _sse(ev)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- source code (fixed allow-list)
SOURCE_GROUPS = [
    ("Ingestion", ["app/ingest/html_parser.py", "app/ingest/chunker.py"]),
    ("Retrieval", ["app/retrieval/resolver.py", "app/retrieval/search.py", "app/retrieval/embedders.py"]),
    ("Chat pipeline", ["app/chat/pipeline.py", "app/chat/prompts.py", "app/chat/citations.py", "app/chat/memory.py"]),
    ("Guardrails", ["app/guards/prefilter.py", "app/guards/ratelimit.py"]),
    ("LLM providers", ["app/llm/base.py", "app/llm/gemini.py", "app/pricing.yaml"]),
    ("API & config", ["app/api.py", "app/config.py"]),
    ("Frontend", ["app/web/index.html", "app/web/app.js", "app/web/styles.css"]),
    ("Evaluation", ["evals/run_retrieval_eval.py", "evals/chunking_eval.py", "evals/calibrate_floor.py",
                    "evals/sweep_bm25_weight.py", "evals/retrieval_cases.yaml"]),
    ("Tests", ["tests/test_ingest.py", "tests/test_resolver.py", "tests/test_embedders.py",
               "tests/test_guards.py", "tests/test_pipeline.py"]),
    ("Project", ["pyproject.toml"]),
]


@lru_cache
def source_index() -> dict[str, dict]:
    out = {}
    for group, paths in SOURCE_GROUPS:
        for p in paths:
            f = ROOT / p
            if f.is_file():
                text = f.read_text(encoding="utf-8")
                out[p] = {"path": p, "group": group, "lines": text.count("\n") + 1, "text": text}
    return out


@app.get("/api/source")
def source_list():
    return [{k: v for k, v in f.items() if k != "text"} for f in source_index().values()]


@app.get("/api/source/file")
def source_file(path: str):
    f = source_index().get(path)  # lookup in the allow-list only; the path is never opened directly
    if not f:
        raise HTTPException(404, "not available")
    return {"path": f["path"], "text": f["text"]}


# ---------------------------------------------------------------- docs & evaluation
DOCS = {"log": "docs/CONVERSATION_LOG.md"}  # the only document shown in the app (Agentic usage)


@app.get("/api/docs/{name}")
def doc(name: str):
    if name not in DOCS:
        raise HTTPException(404, "unknown doc")
    md = (ROOT / DOCS[name]).read_text(encoding="utf-8")
    html = render_markdown(md)
    return {"name": name, "html": html}


def _load(name: str) -> dict | None:
    f = ROOT / "evals" / "results" / name
    return json.loads(f.read_text()) if f.exists() else None


@app.get("/api/scheme")
def scheme():
    """The hand-drawn system diagram, exported from draw.io to scheme/embed.html. Only the embedded PNG is
    served: the export's own onclick handler (which would post the diagram to diagrams.net) is dropped."""
    f = ROOT / "scheme" / "embed.html"
    m = re.search(r'src="(data:image/png;base64,[A-Za-z0-9+/=]+)"', f.read_text()) if f.exists() else None
    if not m:
        return JSONResponse({"error": "no diagram exported yet"}, status_code=404)
    return {"src": m.group(1), "updated": datetime.fromtimestamp(f.stat().st_mtime, UTC).strftime("%Y-%m-%d %H:%M UTC")}


@app.get("/api/evals")
def evals():
    retrieval = {}
    for split in ("dev", "test"):
        for emb in ("local", "gemini1", "gemini2"):
            d = _load(f"retrieval_{split}_{emb}.json")
            if d:
                retrieval[f"{split}_{emb}"] = {"n": d["n_cases"], "metrics": d["metrics"]}
    chunking = {}
    for split in ("dev", "test"):
        d = _load(f"chunking_{split}.json")
        if d:
            chunking[split] = {name: {k: v for k, v in s.items() if not k.endswith("_cases")}
                               for name, s in d["strategies"].items()} | {"_n": d["n_cases"]}
    floors = {e: _load(f"relevance_floor_{e}.json") for e in ("local", "gemini2")}
    return JSONResponse({
        "retrieval": retrieval,
        "chunking": chunking,
        "floors": {e: {k: d[k] for k in ("chosen", "chosen_blocks_off_topic", "chosen_blocks_in_scope",
                                         "in_scope_min", "off_topic_max") if k in d} for e, d in floors.items() if d},
        "bm25_sweep": (_load("bm25_weight_sweep.json") or {}).get("sweep"),
        "generation": _load("model_selection.json"),
        "styles": _load("style_comparison.json"),
    })
