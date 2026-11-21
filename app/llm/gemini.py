"""Gemini provider (google-genai SDK). Calls verified against the installed SDK and by smoke tests:
- Gemini 3.x: no temperature/top_p (deprecated per the 3.8 migration guide); thinking_level instead;
  gemini-3.8-flash rejects "minimal"; flash-lite accepts it.
- thought parts (if any) are filtered from the visible stream.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator

from google import genai
from google.genai import types as t

from .base import LLM, LLMResult, Message, StreamEvent, Usage

_client: genai.Client | None = None
_lock = threading.Lock()


def client() -> genai.Client:
    """One shared client, created once under a lock. Without the lock, concurrent first calls each built a
    client; the losers were garbage-collected, and genai.Client.__del__ closes its HTTP connection, so a
    request in flight on a lost client failed with "client has been closed" (found by the E8 eval)."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _client


def _contents(messages: list[Message]) -> list[t.Content]:
    return [t.Content(role="model" if m.role == "assistant" else "user", parts=[t.Part(text=m.content)])
            for m in messages]


def _usage(model: str, um, started: float) -> Usage:
    thoughts = (um.thoughts_token_count or 0) if um else 0
    return Usage(
        model=model,
        input_tokens=(um.prompt_token_count or 0) if um else 0,
        output_tokens=((um.candidates_token_count or 0) + thoughts) if um else 0,
        thinking_tokens=thoughts,
        latency_s=round(time.perf_counter() - started, 3),
    )


def _visible(resp) -> str:
    out = []
    for cand in resp.candidates or []:
        for p in (cand.content.parts if cand.content else None) or []:
            if p.text and not getattr(p, "thought", False):
                out.append(p.text)
    return "".join(out)


class GeminiLLM(LLM):
    def __init__(self, model: str):
        self.model = model

    def _config(self, system, max_tokens, thinking, json_schema=None):
        kw = {"system_instruction": system, "max_output_tokens": max_tokens}
        if thinking:
            kw["thinking_config"] = t.ThinkingConfig(thinking_level=thinking)
        if json_schema:
            kw["response_mime_type"] = "application/json"
            kw["response_json_schema"] = json_schema
        return t.GenerateContentConfig(**kw)

    def generate(self, system, messages, *, max_tokens, thinking=None, json_schema=None) -> LLMResult:
        started = time.perf_counter()
        r = client().models.generate_content(
            model=self.model, contents=_contents(messages), config=self._config(system, max_tokens, thinking, json_schema)
        )
        finish = str(r.candidates[0].finish_reason) if r.candidates else ""
        return LLMResult(_visible(r), _usage(self.model, r.usage_metadata, started), finish)

    def stream(self, system, messages, *, max_tokens, thinking=None) -> Iterator[StreamEvent]:
        started = time.perf_counter()
        text, last = [], None
        for chunk in client().models.generate_content_stream(
            model=self.model, contents=_contents(messages), config=self._config(system, max_tokens, thinking)
        ):
            last = chunk
            d = _visible(chunk)
            if d:
                text.append(d)
                yield StreamEvent(delta=d)
        finish = str(last.candidates[0].finish_reason) if last and last.candidates else ""
        yield StreamEvent(result=LLMResult("".join(text), _usage(self.model, last.usage_metadata if last else None,
                                                                   started), finish))
