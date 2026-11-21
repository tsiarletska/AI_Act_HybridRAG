"""Deterministic reference resolver.

If the user names a unit of the Act explicitly ("Article 6(2)", "Art. 5(1)(a)",
"Annex III point 4", "recital 47") we fetch it directly instead of relying on
semantic search. Also resolves definition questions ("what is a deployer?")
to the matching Art. 3 definition.
"""

from __future__ import annotations

import re

from app.ingest.chunker import Chunk

_ART = re.compile(
    r"\b(?:article|art\.?)\s*(\d{1,3})"
    r"(?:\s*\(\s*(\d{1,2})\s*\)|\s*(?:paragraph|para\.?|§)\s*(\d{1,2}))?"
    r"(?:\s*\(\s*([a-z])\s*\)|\s*point\s*\(?([a-z])\)?)?",
    re.IGNORECASE,
)
_ANX = re.compile(r"\bannex\s+([IVXL]+)\b(?:[^.?\d]{0,20}?(?:point|section)?\s*\(?(\d{1,2}|[A-C])\)?)?", re.IGNORECASE)
# Reverse word order ("point 8 of Annex III", "paragraph 2 of Article 6") is rewritten to the forward form
# before matching. Found by E8: the English rewrite of translated questions uses this order, and so do people.
_ANX_REV = re.compile(r"\b(point|section)\s*\(?(\d{1,2}|[A-C])\)?\s+of\s+annex\s+([IVXL]+)\b", re.IGNORECASE)
_PARA_REV = re.compile(r"\b(?:paragraph|para\.?)\s*(\d{1,2})\s+of\s+(?:article|art\.?)\s*(\d{1,3})\b", re.IGNORECASE)
_RCT = re.compile(r"\brecitals?\s*\(?(\d{1,3})\)?", re.IGNORECASE)
_DEF_Q = re.compile(
    r"\b(what (?:is|are|does)|define|definition|meaning of|meant by|mean by|stands? for|counts? as|who (?:is|are) (?:a|an|the)?)\b",
    re.IGNORECASE,
)

# Every date of application in the Act is set in Art. 113 ("Entry into force and application").
# A question about *when* something applies brings Art. 113 in as a scope hit (a boost, not an override).
_WHEN = re.compile(
    r"\bwhen (?:do|does|will|shall|did|is|are)\b[^?]{0,80}?\b(?:apply|applies|applicable|start|begin|enter|"
    r"take effect|come into|in force|effective)"
    r"|\b(?:what|which) date|\bby when\b|\bfrom when\b|\bdeadlines?\b|\btimeline\b|\btransition(?:al)? period"
    r"|\b(?:start|begin)s? to apply|\bappl(?:y|ies|icable|ication) (?:from|as of)|\b(?:enter|entry) into (?:force|application)",
    re.IGNORECASE,
)
# "when" as a condition ("When can police use ...", "What must a deployer do when ...") does not match.

MAX_PER_ARTICLE = 6  # when a whole article is referenced, cap the chunks we pull in


def _in_range(point: str, wanted: str) -> bool:
    """'3-5' contains '4'; '4' contains '4'."""
    if not point or not wanted.isdigit():
        return point == wanted
    if "-" in point:
        lo, hi = point.split("-")[:2]
        return lo.isdigit() and hi.isdigit() and int(lo) <= int(wanted) <= int(hi)
    return point == wanted


def _annex_point_key(c: Chunk) -> str:
    # id like anx_III_4, anx_VIII_A_1-5, anx_I_A_1-9_p1 -> the numeric part
    m = re.search(r"_(\d+(?:-\d+)?)(?:_p\d+)?$", c.id)
    return m.group(1) if m else ""


class Resolver:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.by_id = {c.id: c for c in chunks}
        self.by_parent: dict[str, list[Chunk]] = {}
        for c in chunks:
            self.by_parent.setdefault(c.parent, []).append(c)
        self.terms = sorted(
            ((c.term.lower(), c) for c in chunks if c.kind == "definition" and c.term),
            key=lambda x: -len(x[0]),  # longest match first ("AI system" before "system")
        )

    def resolve(self, query: str) -> list[Chunk]:
        return [c for c, _ in self.resolve_scored(query)]

    def resolve_scored(self, query: str) -> list[tuple[Chunk, str]]:
        """Return [(chunk, strength)]: "exact" for a named paragraph/point/recital/definition,
        "scope" for a bare article or annex mentioned inside a longer question."""
        hits: list[tuple[Chunk, str]] = []
        query = _ANX_REV.sub(r"Annex \3 \1 \2", query)
        query = _PARA_REV.sub(r"Article \2(\1)", query)
        bare_query = len(query.split()) <= 8  # "What does Article 50 require?" -> treat as exact
        for m in _ART.finditer(query):
            art, para = m.group(1), m.group(2) or m.group(3)
            point = (m.group(4) or m.group(5) or "").lower()
            parent = f"art_{art}"
            if parent not in self.by_parent:
                continue
            if para:
                pid = f"art_{art}_{para}"
                cands = [c for c in self.by_parent[parent] if c.id == pid or c.id.startswith(pid + "_")]
                if art == "3":  # Art. 3(n) is a definition
                    cands = [c for c in self.by_parent[parent] if c.id == f"art_3_{para}"]
                if point:
                    narrowed = [c for c in cands if c.id == f"{pid}_{point}"]
                    cands = narrowed or cands
                hits += [(c, "exact") for c in cands[:MAX_PER_ARTICLE]]
            else:
                strength = "exact" if bare_query else "scope"
                hits += [(c, strength) for c in self.by_parent[parent][:MAX_PER_ARTICLE]]
        for m in _ANX.finditer(query):
            num, pt = m.group(1).upper(), m.group(2)
            parent = f"anx_{num}"
            cands = self.by_parent.get(parent, [])
            strength = "exact" if bare_query else "scope"
            if pt:
                narrowed = [c for c in cands if (pt.isdigit() and _in_range(_annex_point_key(c), pt))
                            or (not pt.isdigit() and f"_{pt.upper()}_" in c.id + "_")]
                if narrowed:
                    cands, strength = narrowed, "exact"
            hits += [(c, strength) for c in cands[:MAX_PER_ARTICLE]]
        for m in _RCT.finditer(query):
            c = self.by_id.get(f"rct_{m.group(1)}")
            if c:
                hits.append((c, "exact"))
        if _DEF_Q.search(query):
            q = query.lower()
            for term, c in self.terms:
                if re.search(rf"\b{re.escape(term)}s?\b", q):
                    # "What is a deployer?" -> exact; "What is the fine for an AI system that..." -> scope
                    tail = re.sub(r"[^a-z ]", "", q.split(term, 1)[1]).split()
                    strong = len(tail) <= 3 or re.search(r"\b(mean|meaning|definition|defined|define)\b", q)
                    hits.append((c, "exact" if strong else "scope"))
                    break  # the longest matching term only
        if _WHEN.search(query) and "art_113" in self.by_id:
            hits.append((self.by_id["art_113"], "scope"))
        seen, out = set(), []
        for c, strength in hits:
            if c.id not in seen:
                seen.add(c.id)
                out.append((c, strength))
        return out
