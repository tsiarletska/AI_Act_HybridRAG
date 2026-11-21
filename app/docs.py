"""Render the repository's Markdown docs for the web app."""

from __future__ import annotations

import re

import markdown

_LIST = re.compile(r"^(\s*)([-*]|\d+\.)\s")


def _md_compat(md: str) -> str:
    """GitHub-style Markdown -> Python-Markdown: blank line before a list, 4-space nesting."""
    out, prev_list, in_code = [], False, False
    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _LIST.match(line)
        if m:
            indent = len(m.group(1))
            line = " " * (indent * 2) + line.lstrip() if indent else line
            if not prev_list and out and out[-1].strip():
                out.append("")
        elif not in_code and prev_list and line.startswith("  ") and line.strip():
            line = " " * (len(line) - len(line.lstrip())) * 2 + line.lstrip()  # continuation of a nested item
        prev_list = bool(m) or (prev_list and line.startswith(" ") and bool(line.strip()))
        out.append(line)
    return "\n".join(out)


def render_markdown(md: str) -> str:
    return markdown.markdown(_md_compat(md), extensions=["tables", "fenced_code", "sane_lists", "md_in_html"])
