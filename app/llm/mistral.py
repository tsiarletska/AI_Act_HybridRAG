"""Mistral provider (mistralai SDK 3.x, `from mistralai.client import Mistral`). Verified by smoke tests 2026-11-20:
- mistral-large-4 always reasons: reasoning_effort accepts only low/medium/high ("none" is a 400). The pipeline's
  Gemini levels map onto it; "minimal" becomes "low", the lowest available.
- Message content arrives as a list of chunks: ThinkChunk (reasoning, hidden) and TextChunk (visible). Only
  type == "text" chunks are shown.
- usage.completion_tokens already includes reasoning tokens (completion_tokens_details.reasoning_tokens), so it
  is billed as output as is.
- finish_reason "length" is normalised to "MAX_TOKENS" so the pipeline's truncation check works unchanged.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator

from mistralai.client import Mistral

from .base import LLM, LLMResult, Message, StreamEvent, Usage

_client: Mistral | None = None
_lock = threading.Lock()
_EFFORT = {"minimal": "low", "low": "low", "medium": "medium", "high": "high"}
_RETRY_STATUS = {429, 500, 502, 503, 504}


def client() -> Mistral:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = Mistral(api_key=os.environ.get("MISTRAL_API_KEY"))
    return _client


def _visible(content) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    return "".join(getattr(p, "text", "") or "" for p in content if getattr(p, "type", "") == "text")


def _finish(reason) -> str:
    r = str(reason or "")
    return "MAX_TOKENS" if r == "length" else r.upper()


def _usage(model: str, u, started: float) -> Usage:
    details = getattr(u, "completion_tokens_details", None) or {}
    thinking = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0
    return Usage(model=model,
                 input_tokens=(u.prompt_tokens or 0) if u else 0,
                 output_tokens=(u.completion_tokens or 0) if u else 0,
                 thinking_tokens=thinking or 0,
                 latency_s=round(time.perf_counter() - started, 3))


def _retryable(e: Exception) -> bool:
    status = getattr(getattr(e, "raw_response", None), "status_code", None) or getattr(e, "status_code", None)
    return status in _RETRY_STATUS


class MistralLLM(LLM):
    def __init__(self, model: str):
        self.model = model

    def _kw(self, system, messages, max_tokens, thinking, json_schema=None) -> dict:
        msgs = [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in messages]
        kw = {"model": self.model, "messages": msgs, "max_tokens": max_tokens}
        if thinking:
            kw["reasoning_effort"] = _EFFORT.get(thinking, thinking)
        if json_schema:
            kw["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "out", "schema": json_schema, "strict": True}}
        return kw

    def generate(self, system, messages: list[Message], *, max_tokens, thinking=None, json_schema=None) -> LLMResult:
        for attempt in range(4):
            started = time.perf_counter()
            try:
                r = client().chat.complete(**self._kw(system, messages, max_tokens, thinking, json_schema))
                ch = r.choices[0]
                return LLMResult(_visible(ch.message.content), _usage(self.model, r.usage, started),
                                 _finish(ch.finish_reason))
            except Exception as e:
                if attempt == 3 or not _retryable(e):
                    raise
                time.sleep(2 ** attempt * 2)
        raise RuntimeError("unreachable")

    def stream(self, system, messages: list[Message], *, max_tokens, thinking=None) -> Iterator[StreamEvent]:
        kw = self._kw(system, messages, max_tokens, thinking)
        for attempt in range(4):
            started = time.perf_counter()
            text, usage, finish, sent = [], None, "", False
            try:
                for ev in client().chat.stream(**kw):
                    d = ev.data
                    if d.usage:
                        usage = d.usage
                    ch = d.choices[0] if d.choices else None
                    if ch is None:
                        continue
                    if ch.finish_reason:
                        finish = _finish(ch.finish_reason)
                    v = _visible(ch.delta.content if ch.delta else None)
                    if v:
                        sent = True
                        text.append(v)
                        yield StreamEvent(delta=v)
                yield StreamEvent(result=LLMResult("".join(text), _usage(self.model, usage, started), finish))
                return
            except Exception as e:
                # retry only if nothing was shown yet; a half-streamed answer cannot be taken back
                if sent or attempt == 3 or not _retryable(e):
                    raise
                time.sleep(2 ** attempt * 2)
