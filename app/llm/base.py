"""Provider-neutral LLM interface. The pipeline only talks to this; Gemini and Mistral plug in."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass
class Usage:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0  # visible output + thinking (both billed as output)
    thinking_tokens: int = 0
    latency_s: float = 0.0

    def cost_usd(self, on: date | None = None) -> float:
        p = price(self.model, on)
        return round((self.input_tokens * p["input"] + self.output_tokens * p["output"]) / 1e6, 6)


@dataclass
class LLMResult:
    text: str
    usage: Usage
    finish_reason: str = ""


@dataclass
class StreamEvent:
    delta: str = ""
    result: LLMResult | None = None  # set on the final event only


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


class LLM:
    """generate() for guard/eval calls; stream() for the chat answer."""

    model: str = ""

    def generate(self, system: str, messages: list[Message], *, max_tokens: int, thinking: str | None = None,
                 json_schema: dict | None = None) -> LLMResult:
        raise NotImplementedError

    def stream(self, system: str, messages: list[Message], *, max_tokens: int,
               thinking: str | None = None) -> Iterator[StreamEvent]:
        raise NotImplementedError


@lru_cache
def _prices() -> dict:
    return yaml.safe_load((Path(__file__).parents[1] / "pricing.yaml").read_text())


def price(model: str, on: date | None = None) -> dict:
    rows = _prices().get(model)
    if not rows:
        return {"input": 0.0, "output": 0.0}
    today = (on or date.today()).isoformat()
    valid = [r for r in rows if r["from"] <= today] or rows[:1]
    return valid[-1]


def make_llm(model: str) -> LLM:
    if model.startswith("gemini"):
        from .gemini import GeminiLLM

        return GeminiLLM(model)
    if model.startswith(("mistral", "ministral", "magistral")):
        from .mistral import MistralLLM

        return MistralLLM(model)
    raise ValueError(f"unknown model {model}")
