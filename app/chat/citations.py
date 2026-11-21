"""Citation parsing and validation (PLAN §2.5).

The model cites by copying a chunk label in square brackets, e.g. [Art. 5(1)(f)] or
[Annex VIII, Section A, points 1–5]. Labels are normalised before lookup so harmless
variants still resolve: "Article 5(1)" ~ "Art. 5(1)", hyphen ~ en dash, spacing, case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingest.chunker import Chunk

CITE = re.compile(r"\[([^\[\]\n]{2,80})\]")


def norm(label: str) -> str:
    s = label.strip().lower()
    s = re.sub(r"\barticles?\b\.?", "art.", s)
    s = re.sub(r"\bart\b\.?", "art.", s)
    s = re.sub(r"\brecitals?\b", "recital", s)
    s = s.replace("–", "-").replace("—", "-").replace("‑", "-")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s*\(\s*", "(", s)
    s = re.sub(r"\s*\)", ")", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"art\.\s*", "art. ", s)
    return s


@dataclass
class Citation:
    label: str  # as written by the model
    valid: bool
    chunk_id: str = ""
    url: str = ""


def label_map(chunks: list[Chunk]) -> dict[str, Chunk]:
    out: dict[str, Chunk] = {}
    for c in chunks:
        out.setdefault(norm(c.label), c)
    return out


# trailing sub-point, a sub-point range "(a)-(c)", or a dotted sub-point "4.3" (Annex VII numbering)
_SUB = re.compile(r"\([a-z0-9]{1,4}\)(?:-\([a-z0-9]{1,4}\))?$|(?<=\d)\.\d+$")
# trailing ", point 3" / ", points 1-4" / ", point(a)" (norm() removes the space before "(") / ", section 2"
_TAIL = re.compile(r", (?:points?|section|part)\b[^,]*$")
_POINT = re.compile(r"^(?P<prefix>.+), points? (?P<a>\d+)(?:-(?P<b>\d+))?$")


def _in_sent_range(n: str, lm: dict[str, Chunk]) -> Chunk | None:
    """'Annex XI, Section 2, point 2' is inside the sent excerpt 'Annex XI, Section 2, points 1-3'."""
    m = _POINT.match(n)
    if not m:
        return None
    a = int(m["a"])
    b = int(m["b"] or a)
    for key, chunk in lm.items():
        k = _POINT.match(key)
        if k and k["prefix"] == m["prefix"] and k["b"] and int(k["a"]) <= a and b <= int(k["b"]):
            return chunk
    return None


def _parent_of_sent(n: str, lm: dict[str, Chunk]) -> Chunk | None:
    """'Art. 17(1)' when only its points 'Art. 17(1)(a)', '(c)', '(d)' were sent: the citation names the
    paragraph whose points the model read, so it is valid and links to the first of them."""
    if not n.startswith("art."):
        return None
    kids = [k for k in lm if k.startswith(n + "(")]
    return lm[min(kids)] if kids else None


def resolve(n: str, lm: dict[str, Chunk]) -> Chunk | None:
    """Exact label, else a citation that narrows a retrieved excerpt, which is valid and links to it:
    trailing sub-points removed ("Art. 26(7)(a)" from "Art. 26(7)", "Annex III, point 1(c)" from
    "Annex III, point 1"), a point inside a sent range ("Annex XI, Section 2, point 2" from
    "..., points 1-3"), or a part of a whole annex or section ("Annex VI, points 1-4" from "Annex VI")."""
    stripped_tail, written = False, n
    while n:
        # a lead-in chunk ("Annex III": 18 words, points in their own chunks) does not contain its points
        if n in lm and not (stripped_tail and lm[n].id.endswith("_intro")):
            return lm[n]
        if c := _in_sent_range(n, lm):
            return c
        if n == written and (c := _parent_of_sent(n, lm)):  # only as written: never after stripping
            return c
        if m := _SUB.search(n):
            n = n[: m.start()].rstrip()
        elif m := _TAIL.search(n):
            n, stripped_tail = n[: m.start()].rstrip(), True
        else:
            return None
    return None


_START = r"(?:art\.?|article|annex|recital)\b"


def _parts(inner: str) -> list[str]:
    """Split one bracket into labels.
    '[Art. 5(1)(a); Art. 6(2)]' and '[Art. 68(2), Art. 68(2)(a)]' -> two labels each. A comma splits only
    before a new 'Art.'/'Annex'/'Recital', because commas are also part of annex labels ('Annex III, point 4').
    Shorthand lists continue the previous label: '[Art. 53(1)(b), (b)(i)]' -> 'Art. 53(1)(b)', 'Art. 53(1)(b)(i)';
    '[Annex XII, point 1(d), (e)]' -> '... point 1(d)', '... point 1(e)'; 'and (c)' works the same way."""
    out: list[str] = []
    for chunk in re.split(r";|\s/\s", inner):  # '[Art. 36(8) / Art. 36(5)]' is two labels too
        pieces = re.split(rf"\s*,\s*(?={_START})|\s*(?:,|\band\b)\s*(?=\()", chunk.strip(), flags=re.IGNORECASE)
        for p in (x.strip() for x in pieces):
            if not p:
                continue
            if p.startswith("(") and out:
                prev = out[-1]
                first = re.match(r"\([^()]{1,4}\)", p)
                if first and (i := prev.rfind(first.group(0))) > 0:  # '(b)(ii)' after '...(1)(b)(i)': same level as '(b)'
                    base = prev[:i]
                else:  # '(e)' after '... point 1(d)': replaces the last sub-point
                    base = prev[: m.start()] if (m := re.search(r"\([^()]{1,4}\)$", prev)) else prev
                p = base + p
            out.append(p)
    return out


def looks_like_citation(s: str) -> bool:
    return bool(re.match(r"(?i)\s*(art\.?|article|annex|recital)\b", s))


def brackets(text: str, allowed: list[Chunk]) -> dict[str, list[dict]]:
    """Per bracket as written ('Art. 68(2), Art. 68(2)(a)'), the labels it holds and the server's verdict on each,
    so the browser draws exactly what was validated here instead of re-parsing the text with its own rules."""
    lm, out = label_map(allowed), {}
    for m in CITE.finditer(text):
        inner = m.group(1)
        parts = _parts(inner)
        if inner in out or not parts or not all(looks_like_citation(p) for p in parts):
            continue
        out[inner] = [{"label": p, "valid": bool(c := resolve(norm(p), lm)),
                       "url": c.url if c else "", "header": c.header if c else ""} for p in parts]
    return out


def extract(text: str, allowed: list[Chunk]) -> list[Citation]:
    """Citations in order of first appearance; valid = label is in the retrieved set."""
    lm = label_map(allowed)
    seen, out = set(), []
    for m in CITE.finditer(text):
        for lab in _parts(m.group(1)):
            if not looks_like_citation(lab) or lab in seen:
                continue
            seen.add(lab)
            c = resolve(norm(lab), lm)
            out.append(Citation(lab, bool(c), c.id if c else "", c.url if c else ""))
    return out
