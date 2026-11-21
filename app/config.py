"""Runtime settings (env vars override; .env is loaded by `uv run --env-file .env` or the platform)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

CORPUS = {
    "title": "Regulation (EU) 2024/1689 (Artificial Intelligence Act)",
    "version": "Original text, Official Journal L, 12.7.2024",
    "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng",
    "notice": "Answers are based on the original 2024 text. Later amendments (e.g. the 2026 'Digital Omnibus' "
              "changes to high-risk deadlines) are not reflected.",
}


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass
class Settings:
    # models (verified via the list-models API and model pages on 2026-11-18)
    answer_model: str = field(default_factory=lambda: os.environ.get("ANSWER_MODEL", "gemini-3.8-flash"))
    answer_thinking: str = field(default_factory=lambda: os.environ.get("ANSWER_THINKING", "low"))
    guard_model: str = field(default_factory=lambda: os.environ.get("GUARD_MODEL", "gemini-3.5-flash-lite"))
    guard_thinking: str = field(default_factory=lambda: os.environ.get("GUARD_THINKING", "minimal"))
    answer_max_tokens: int = field(default_factory=lambda: _int("ANSWER_MAX_TOKENS", 2048))
    guard_max_tokens: int = field(default_factory=lambda: _int("GUARD_MAX_TOKENS", 400))
    # retrieval
    top_k: int = field(default_factory=lambda: _int("TOP_K", 8))
    context_words: int = field(default_factory=lambda: _int("CONTEXT_WORDS", 3000))
    # memory
    history_turns: int = field(default_factory=lambda: _int("HISTORY_TURNS", 4))
    max_turns_per_session: int = field(default_factory=lambda: _int("MAX_TURNS_PER_SESSION", 30))
    db_path: str = field(default_factory=lambda: os.environ.get("DB_PATH", "data/app.sqlite3"))
    # protection of the token budget on a public URL
    max_input_chars: int = field(default_factory=lambda: _int("MAX_INPUT_CHARS", 2000))
    per_ip_per_minute: int = field(default_factory=lambda: _int("RATE_PER_MINUTE", 8))
    per_ip_per_day: int = field(default_factory=lambda: _int("RATE_PER_DAY", 100))
    global_per_day: int = field(default_factory=lambda: _int("GLOBAL_PER_DAY", 1500))


settings = Settings()
