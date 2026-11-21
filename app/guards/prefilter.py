"""Deterministic pre-filter (guardrail step 2): no LLM call for obvious misuse.

Patterns are deliberately narrow (imperative requests at the start of the message), so that
in-scope questions *about* code or AI ("Does the Act apply to systems that generate code?")
are not blocked. Covered by tests/test_guards.py with in-scope negatives.
"""

from __future__ import annotations

import re

_CODE_REQUEST = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+)?(?:write|generate|create|implement|build|code|fix|debug|refactor|"
    r"give me|show me)\b[^?.]{0,60}?\b(?:code|script|snippet|(?:a|an)\s+(?:[\w+#-]+\s+){0,3}function|sql|regex|html|css|javascript|typescript|"
    r"python|java|c\+\+|bash|dockerfile)\b",
    re.IGNORECASE,
)
# Only code-specific nouns: "app", "website", "api", "class", "algorithm", "query" also occur in in-scope
# requests ("a compliance checklist for my app", "the risk class of ...") and must not trigger a refusal.
_CODE_BLOCK = re.compile(r"```|^\s*(?:def |class |import |from \w+ import |#include|public static void)", re.MULTILINE)
_INJECTION = re.compile(
    r"ignore (?:all |any |the )?(?:previous|above|prior|earlier) (?:instructions|prompts?|rules)"
    r"|disregard (?:your|the|all) (?:instructions|rules|system prompt)"
    r"|(?:reveal|show|print|repeat) (?:me )?(?:your|the) (?:system prompt|instructions|hidden prompt)"
    r"|you are now (?:a|an|in)\b|\bjailbreak\b|\bDAN mode\b|developer mode",
    re.IGNORECASE,
)

REPLIES = {
    "code": "I can only answer questions about the EU AI Act (Regulation (EU) 2024/1689), so I can't help with "
            "writing or fixing code. You could ask, for example, what the Act requires from providers of "
            "general-purpose AI models.",
    "injection": "I can only answer questions about the EU AI Act, based on its text. Please ask a question about "
                 "the regulation.",
    "too_long": "Your message is too long. Please ask a shorter question (up to {n} characters).",
    "empty": "Please type a question about the EU AI Act.",
}


def check(text: str, max_chars: int) -> str | None:
    """Return a reason key if the message must be refused without an LLM call, else None."""
    if not text.strip():
        return "empty"
    if len(text) > max_chars:
        return "too_long"
    if _INJECTION.search(text):
        return "injection"
    if _CODE_REQUEST.search(text) or _CODE_BLOCK.search(text):
        return "code"
    return None
