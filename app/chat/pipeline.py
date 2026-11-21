"""The chat pipeline: one code path for the web UI (streaming) and the evals (non-streaming).

Order, cheapest first (PLAN §2.4):
  1. pre-filter (regex, length)                       no LLM
  2. relevance floor on a FIRST turn (raw question)   one embedding call
  3. guard: rewrite follow-up + classify scope        cheap LLM, JSON
  4. relevance floor on the standalone question (follow-ups), retrieval, citation carry-over
  5. answer (streamed in the UI)                      answer LLM
  6. post-check: citations valid? code fences? -> flagged in the UI; one retry in the non-streaming path
  7. memory: both turns saved with usage, cost and sources
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field

from app.chat import citations as cit
from app.chat.memory import Memory
from app.chat.prompts import (DEFAULT_STYLE, GUARD_SCHEMA, GUARD_SYSTEM, answer_system, answer_user_message,
                              guard_user_message)
from app.config import Settings
from app.guards import prefilter
from app.ingest.chunker import Chunk
from app.llm.base import LLM, Message, Usage

log = logging.getLogger(__name__)

OUT_OF_SCOPE = ("I can only answer questions about the EU AI Act (Regulation (EU) 2024/1689). "
                "Try asking, for example, which AI practices are prohibited, what providers of high-risk "
                "systems must do, or what a 'deployer' is.")
NOT_ADDRESSED = "do not address"
_FENCE = re.compile(r"```.*?(```|$)", re.DOTALL)


@dataclass
class Prepared:
    kind: str  # answer | refusal | clarification
    message: str
    standalone: str = ""
    reply: str = ""  # for refusal / clarification
    stage: str = ""  # which step decided: prefilter | floor | guard | guard_error
    hits: list[Chunk] = field(default_factory=list)
    guard: dict = field(default_factory=dict)
    usage: list[Usage] = field(default_factory=list)
    top_similarity: float | None = None
    style: str = DEFAULT_STYLE  # answer style from the UI toggle: legal | plain
    timings: dict = field(default_factory=dict)  # ms per step (E7/E9 latency); recording only, no behaviour


def _source(c: Chunk) -> dict:
    return {"id": c.id, "label": c.label, "url": c.url, "header": c.header, "kind": c.kind}


def postcheck(text: str, hits: list[Chunk]) -> tuple[str, list[cit.Citation], list[str]]:
    clean = _FENCE.sub("[code removed]", text)
    cites = cit.extract(clean, hits)
    issues = []
    if clean != text:
        issues.append("code_removed")
    if any(not c.valid for c in cites):
        issues.append("invalid_citation")
    if not cites and NOT_ADDRESSED not in clean.lower():
        issues.append("no_citation")
    return clean, cites, issues


class ChatService:
    def __init__(self, retriever, answer_llm: LLM, guard_llm: LLM, memory: Memory, settings: Settings):
        self.r, self.answer_llm, self.guard_llm, self.mem, self.s = retriever, answer_llm, guard_llm, memory, settings

    # ------------------------------------------------------------------ helpers
    def _history(self, sid: str) -> list[dict]:
        return [h for h in self.mem.history(sid, limit=self.s.history_turns * 2)]

    def _below_floor(self, top: float | None) -> bool:
        return top is not None and top < self.r.relevance_floor  # None: embeddings unavailable, skip

    def _select(self, query: str, history: list[dict]) -> tuple[list[Chunk], float | None]:
        found, top = self.r.retrieve(query, k=self.s.top_k)  # thread-safe: no shared state
        hits = [h.chunk for h in found]
        # citation carry-over: what the previous answer cited stays available for the follow-up
        prev = next((h for h in reversed(history) if h["role"] == "assistant" and h["kind"] == "answer"), None)
        have = {c.id for c in hits}
        for cid in (prev["cited_ids"] if prev else [])[:3]:
            c = self.r.get(cid)
            if c and cid not in have:
                hits.append(c)
                have.add(cid)
        out, words = [], 0
        for c in hits:  # context budget
            if out and words + c.words > self.s.context_words:
                continue
            out.append(c)
            words += c.words
        return out, top

    # ------------------------------------------------------------------ steps 1-4
    def prepare(self, message: str, history: list[dict]) -> Prepared:
        p = Prepared(kind="answer", message=message)
        t = time.perf_counter()
        reason = prefilter.check(message, self.s.max_input_chars)
        p.timings["prefilter"] = (time.perf_counter() - t) * 1000
        if reason:
            p.kind, p.stage = "refusal", "prefilter"
            p.reply = prefilter.REPLIES[reason].format(n=self.s.max_input_chars)
            return p

        if not history:  # first turn: the raw message is the question, the floor applies directly
            t = time.perf_counter()
            _, p.top_similarity = self.r.retrieve(message, k=1)
            p.timings["floor"] = (time.perf_counter() - t) * 1000
            if self._below_floor(p.top_similarity):
                p.kind, p.stage, p.reply = "refusal", "floor", OUT_OF_SCOPE
                return p

        t = time.perf_counter()
        try:
            g = self.guard_llm.generate(GUARD_SYSTEM, [Message("user", guard_user_message(history, message))],
                                        max_tokens=self.s.guard_max_tokens, thinking=self.s.guard_thinking,
                                        json_schema=GUARD_SCHEMA)
            p.usage.append(g.usage)
            p.guard = json.loads(g.text)
        except Exception as e:  # fail open to "in": the floor and the answer prompt still constrain it
            log.warning("guard failed (%s); treating as in-scope", type(e).__name__)
            p.guard, p.stage = {"label": "in", "standalone_question": message, "reason": "guard error"}, "guard_error"
        p.timings["guard"] = (time.perf_counter() - t) * 1000

        label = p.guard.get("label", "in")
        p.standalone = (p.guard.get("standalone_question") or message).strip()
        if label == "out":
            p.kind, p.stage, p.reply = "refusal", "guard", OUT_OF_SCOPE
            return p
        if label == "ambiguous" and p.guard.get("clarification"):
            p.kind, p.stage, p.reply = "clarification", "guard", p.guard["clarification"]
            return p

        t = time.perf_counter()
        p.hits, p.top_similarity = self._select(p.standalone, history)
        p.timings["retrieve"] = (time.perf_counter() - t) * 1000
        if history and self._below_floor(p.top_similarity):  # follow-ups: the floor applies to the rewritten question
            p.kind, p.stage, p.reply, p.hits = "refusal", "floor", OUT_OF_SCOPE, []
        return p

    # ------------------------------------------------------------------ step 5
    def _answer_messages(self, p: Prepared, history: list[dict]) -> list[Message]:
        msgs = []
        for h in history:
            if h["kind"] in ("answer", "clarification") or h["role"] == "user":
                msgs.append(Message(h["role"], h["content"]))
        # a refusal in history leaves a dangling user turn: keep strict user/assistant alternation
        cleaned: list[Message] = []
        for m in msgs:
            if cleaned and cleaned[-1].role == m.role:
                cleaned[-1] = m
            else:
                cleaned.append(m)
        if cleaned and cleaned[-1].role == "user":
            cleaned.pop()
        return cleaned + [Message("user", answer_user_message(p.standalone, p.hits))]

    # ------------------------------------------------------------------ public API
    def stream(self, sid: str, message: str, style: str = DEFAULT_STYLE) -> Iterator[dict]:
        """Events: meta, delta*, done — or a single final event for refusals/clarifications."""
        system = answer_system(style)  # raises on an unknown style before any work is done
        t0 = time.perf_counter()
        if self.mem.user_turns(sid) >= self.s.max_turns_per_session:
            yield {"type": "final", "kind": "refusal",
                   "text": "This conversation has reached its length limit. Please start a new conversation."}
            return
        history = self._history(sid)
        p = self.prepare(message, history)
        p.style = style
        if p.kind != "answer":
            yield from self._finish_non_answer(sid, p, t0)
            return

        yield {"type": "meta", "standalone": p.standalone, "sources": [_source(c) for c in p.hits]}
        result = None
        t = time.perf_counter()
        try:
            for ev in self.answer_llm.stream(system, self._answer_messages(p, history),
                                             max_tokens=self.s.answer_max_tokens, thinking=self.s.answer_thinking):
                if ev.result:
                    result = ev.result
                else:
                    if "answer_first_token" not in p.timings:
                        p.timings["answer_first_token"] = (time.perf_counter() - t) * 1000
                        p.timings["time_to_first_token"] = (time.perf_counter() - t0) * 1000
                    yield {"type": "delta", "text": ev.delta}
            p.timings["answer"] = (time.perf_counter() - t) * 1000
        except Exception as e:
            log.exception("answer stream failed")
            self.mem.add(sid, "user", message, standalone=p.standalone, kind="answer")
            self.mem.add(sid, "assistant", "The answer service is temporarily unavailable.", kind="error",
                         meta={"error": type(e).__name__})
            yield {"type": "error", "text": "The answer service is temporarily unavailable. Please try again."}
            return
        yield self._finish_answer(sid, p, result, t0)

    def ask(self, sid: str, message: str, style: str = DEFAULT_STYLE) -> dict:
        """Non-streaming path for evals: same steps; one retry if the post-check fails."""
        system = answer_system(style)
        t0 = time.perf_counter()
        history = self._history(sid)
        p = self.prepare(message, history)
        p.style = style
        if p.kind != "answer":
            return list(self._finish_non_answer(sid, p, t0))[-1]
        msgs = self._answer_messages(p, history)
        result = None
        for attempt in range(2):
            result = self.answer_llm.generate(system, msgs, max_tokens=self.s.answer_max_tokens,
                                              thinking=self.s.answer_thinking)
            p.usage.append(result.usage)
            _, _, issues = postcheck(result.text, p.hits)
            if not issues or attempt == 1:
                break
            msgs = msgs + [Message("assistant", result.text),
                           Message("user", "Your answer broke the rules (" + ", ".join(issues) + "). Answer again, "
                                   "citing only the excerpt labels given, in square brackets, without code.")]
        ev = self._finish_answer(sid, p, result, t0, usage_already_added=True)
        ev["retried"] = len([u for u in p.usage if u.model == self.answer_llm.model]) > 1
        return ev

    # ------------------------------------------------------------------ step 6-7
    def _finish_non_answer(self, sid, p: Prepared, t0) -> Iterator[dict]:
        meta = self._meta(p, t0)
        self.mem.add(sid, "user", p.message, standalone=p.standalone, kind=p.kind)
        self.mem.add(sid, "assistant", p.reply, kind=p.kind, meta=meta)
        yield {"type": "final", "kind": p.kind, "text": p.reply, "stage": p.stage, "standalone": p.standalone,
               **meta}

    def _finish_answer(self, sid, p: Prepared, result, t0, usage_already_added=False) -> dict:
        if not usage_already_added:
            p.usage.append(result.usage)
        t = time.perf_counter()
        text, cites, issues = postcheck(result.text, p.hits)
        p.timings["postcheck"] = (time.perf_counter() - t) * 1000
        if result.finish_reason.endswith("MAX_TOKENS"):
            issues.append("truncated")
        meta = self._meta(p, t0) | {"issues": issues, "sources": [_source(c) for c in p.hits],
                                    "brackets": cit.brackets(text, p.hits)}
        valid_ids = [c.chunk_id for c in cites if c.valid]
        self.mem.add(sid, "user", p.message, standalone=p.standalone, kind="answer")
        self.mem.add(sid, "assistant", text, kind="answer", cited_ids=valid_ids, meta=meta)
        return {"type": "done", "kind": "answer", "text": text, "standalone": p.standalone,
                "citations": [asdict(c) for c in cites], **meta}

    def _meta(self, p: Prepared, t0) -> dict:
        return {
            "stage": p.stage,
            "style": p.style,
            "guard": p.guard,
            "top_similarity": None if p.top_similarity is None else round(p.top_similarity, 3),
            "usage": [asdict(u) | {"cost_usd": u.cost_usd()} for u in p.usage],
            "cost_usd": round(sum(u.cost_usd() for u in p.usage), 6),
            "latency_s": round(time.perf_counter() - t0, 2),
            "timings_ms": {k: round(v, 1) for k, v in p.timings.items()},
        }
