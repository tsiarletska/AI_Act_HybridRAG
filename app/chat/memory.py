"""Conversation memory in SQLite (requirement 1). One connection per call: safe across threads."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL,              -- user | assistant
  content TEXT NOT NULL,
  standalone TEXT DEFAULT '',      -- rewritten question (user turns)
  kind TEXT DEFAULT 'answer',      -- answer | refusal | clarification | error
  cited_ids TEXT DEFAULT '[]',
  meta TEXT DEFAULT '{}',          -- usage, cost, latency, sources (assistant turns)
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_session ON messages(session_id, id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Memory:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._mem = sqlite3.connect(":memory:", check_same_thread=False) if path == ":memory:" else None
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        return self._mem if self._mem else closing(sqlite3.connect(self.path))

    def _exec(self, sql, args=()):
        if self._mem:
            cur = self._mem.execute(sql, args)
            self._mem.commit()
            return cur.fetchall()
        with closing(sqlite3.connect(self.path)) as c:
            rows = c.execute(sql, args).fetchall()
            c.commit()
            return rows

    def new_session(self) -> str:
        sid = uuid.uuid4().hex
        self._exec("INSERT INTO sessions VALUES (?, ?)", (sid, _now()))
        return sid

    def exists(self, sid: str) -> bool:
        return bool(self._exec("SELECT 1 FROM sessions WHERE id = ?", (sid,)))

    def add(self, sid: str, role: str, content: str, *, standalone: str = "", kind: str = "answer",
            cited_ids: list[str] | None = None, meta: dict | None = None) -> None:
        self._exec(
            "INSERT INTO messages (session_id, role, content, standalone, kind, cited_ids, meta, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, role, content, standalone, kind, json.dumps(cited_ids or []), json.dumps(meta or {}), _now()),
        )

    def history(self, sid: str, limit: int = 100) -> list[dict]:
        rows = self._exec(
            "SELECT role, content, standalone, kind, cited_ids, meta FROM messages WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?", (sid, limit))
        return [
            {"role": r[0], "content": r[1], "standalone": r[2], "kind": r[3],
             "cited_ids": json.loads(r[4]), "meta": json.loads(r[5])}
            for r in reversed(rows)
        ]

    def user_turns(self, sid: str) -> int:
        return self._exec("SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'", (sid,))[0][0]
