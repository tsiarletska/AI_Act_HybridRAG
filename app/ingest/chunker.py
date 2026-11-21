"""Turn parsed units into retrieval chunks.

Chunking follows the legal structure (never fixed token windows):
  * recital                        -> 1 chunk            rct_47        "Recital 47"
  * article paragraph              -> 1 chunk            art_6_2       "Art. 6(2)"
  * long paragraph with points     -> 1 chunk per point  art_5_1_a     "Art. 5(1)(a)"
                                      (lead-in sentence prefixed to each point)
  * Art. 3 definitions             -> 1 chunk per term   art_3_1       "Art. 3(1)"
  * article without numbered para. -> 1 chunk (or points) art_4        "Art. 4"
  * annex                          -> 1 chunk, or 1 per top-level point
                                                         anx_III_1     "Annex III(1)"
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .html_parser import ELI_URL, Document, Unit, paragraphs, parse, segments, text_of

MAX_WORDS = 350  # above this, a paragraph/annex with points is split by point


@dataclass
class Chunk:
    id: str
    kind: str  # recital | article | definition | annex
    label: str  # citation label, e.g. "Art. 5(1)(a)"
    text: str  # body text (what the LLM sees)
    header: str  # structural context, e.g. "Chapter II Prohibited AI practices > Article 5 ..."
    url: str
    parent: str  # art_5 | anx_III | rct_47
    article: str = ""
    paragraph: str = ""
    point: str = ""
    title: str = ""
    term: str = ""  # defined term for Art. 3 chunks
    refs: list[str] = field(default_factory=list)
    words: int = 0

    @property
    def index_text(self) -> str:
        """Text used for BM25/embeddings: header + label + body."""
        return f"{self.header}\n{self.label}\n{self.text}"


# ---------------------------------------------------------------- references
_ART_REF = re.compile(r"\bArticles? (\d+)((?:\(\d+\))?)")
_ART_LIST = re.compile(r"\bArticles ((?:\d+(?:\(\d+\))?(?:, | and | or | to ))+\d+(?:\(\d+\))?)")
_OTHER_ACT = re.compile(r"(?:\(\d+\)|\([a-z]\)|,? first subparagraph|,? point \([a-z]\))*\s+of (?:Regulation|Directive|Decision)")
_ANX_REF = re.compile(r"\bAnnex(?:es)? ([IVXL]+)\b")


def extract_refs(text: str, self_parent: str = "") -> list[str]:
    """Find outgoing references ('Article 6(2)', 'Articles 8 to 15', 'Annex III')."""
    refs: list[str] = []
    for m in _ART_LIST.finditer(text):
        nums = re.findall(r"\d+(?=\(|\b)", m.group(1))
        items = [int(n) for n in nums if not re.search(rf"\({n}\)", m.group(1))]
        if " to " in m.group(1) and len(items) == 2 and items[1] - items[0] < 30:
            items = list(range(items[0], items[1] + 1))
        refs += [f"art_{n}" for n in items]
    for m in _ART_REF.finditer(text):
        if _OTHER_ACT.match(text, m.end()):  # "Article 17 of Regulation (EU) 2018/1139"
            continue
        n, p = m.group(1), m.group(2)
        refs.append(f"art_{n}_{p.strip('()')}" if p else f"art_{n}")
    refs += [f"anx_{r}" for r in _ANX_REF.findall(text)]
    seen, out = set(), []
    for r in refs:
        if r not in seen and r != self_parent:
            seen.add(r)
            out.append(r)
    return out


def _point_key(label: str) -> str:
    """'(a)' -> 'a', '1.' -> '1', '(iv)' -> 'iv'."""
    return label.strip().strip("().").strip()


def _wc(t: str) -> int:
    return len(t.split())


# ---------------------------------------------------------------- builders
def _article_header(u: Unit) -> str:
    parts = []
    if u.chapter:
        parts.append(f"Chapter {u.chapter} {u.chapter_title}".strip())
    if u.section:
        parts.append(f"Section {u.section} {u.section_title}".strip())
    parts.append(f"Article {u.number} {u.title}".strip())
    return " > ".join(parts)


def _split_points(segs, base_id, base_label, lead_prefix=True):
    """Yield (id, label, point_key, text) for each point; free text is merged.

    The first free-text segment (lead-in) is prefixed to every point so each chunk
    stays understandable on its own. Later free-text segments become their own chunk.
    """
    lead = ""
    out = []
    extra = 0
    for i, (label, text) in enumerate(segs):
        if label == "text":
            if i == 0:
                lead = text
            else:
                extra += 1
                out.append((f"{base_id}_s{extra}", base_label, "", text))
        else:
            k = _point_key(label)
            body = f"{lead}\n{text}" if (lead and lead_prefix) else text
            out.append((f"{base_id}_{k}", f"{base_label}({k})", k, body))
    if lead and not any(lbl != "text" for lbl, _ in segs):
        out.insert(0, (base_id, base_label, "", lead))
    return out


_SECTION = re.compile(r"^Section ([A-Z0-9]+)\b")
_NUM_HEAD = re.compile(r"^(\d+)\.\s")
_LETTER = re.compile(r"^\(?([a-z]|[ivx]+)\)$")
_LINE_SPLIT = re.compile(r"^(?:Section [A-Z0-9]+\b|\d+(?:\.\d+)*\.\s)")
PACK_WORDS = 150  # tiny consecutive list items (e.g. Annex VIII) are packed together
TINY = 60


def _annex_label(n: str, section: str | None, points: list[str]) -> str:
    label = f"Annex {n}"
    if section:
        label += f", Section {section}"
    if points:
        pts = [p for p in points if p]
        if len(pts) == 1:
            label += f", point {pts[0]}"
        elif pts:
            label += f", points {pts[0]}–{pts[-1]}"
    return label


def _split_long(text: str) -> list[str]:
    """Split an oversized text at numbered/section lines, packing up to MAX_WORDS."""
    pieces, cur = [], []
    for line in text.split("\n"):
        if _LINE_SPLIT.match(line) and cur:
            pieces.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        pieces.append("\n".join(cur))
    fine: list[str] = []
    for p in pieces:  # a piece still too long (no sub-headings) is split by lines
        if _wc(p) <= MAX_WORDS:
            fine.append(p)
            continue
        cur_lines: list[str] = []
        for line in p.split("\n"):
            if cur_lines and _wc("\n".join(cur_lines)) + _wc(line) > MAX_WORDS:
                fine.append("\n".join(cur_lines))
                cur_lines = []
            cur_lines.append(line)
        if cur_lines:
            fine.append("\n".join(cur_lines))
    packed, buf = [], ""
    for p in fine:
        if buf and _wc(buf) + _wc(p) > MAX_WORDS:
            packed.append(buf)
            buf = p
        else:
            buf = f"{buf}\n{p}" if buf else p
    if buf:
        packed.append(buf)
    return packed


def _annex_chunks(u: Unit) -> list[Chunk]:
    """Section-aware annex chunking.

    Handles three layouts found in the Act: numbered points grouped in sections
    (Annex VIII, XI), numbered headings with lettered sub-points (Annex X) and
    plain text with numbered lines (Annex I, VII).
    """
    header = f"Annex {u.number} {u.title}".strip()
    segs = segments(u.element, skip_classes=("oj-doc-ti",))
    full = "\n".join(t for _, t in segs)
    base = dict(parent=u.id, title=u.title, header=header, url=f"{ELI_URL}#{u.id}")
    if _wc(full) <= MAX_WORDS:
        return [Chunk(id=u.id, kind="annex", label=f"Annex {u.number}", text=full, **base)]

    # 1) group segments into items keyed by (section, point)
    items: list[dict] = []
    section: str | None = None
    expanded: list[tuple[str, str]] = []
    for label, text in segs:
        if label == "text":
            expanded += [("text", t) for t in re.split(r"\n(?=Section [A-Z0-9]+\b)", text) if t.strip()]
        else:
            expanded.append((label, text))
    for label, text in expanded:
        if label == "text":
            ms, mn = _SECTION.match(text), _NUM_HEAD.match(text)
            if ms:
                section = ms.group(1)
                items.append({"section": section, "point": "", "text": text})
            elif mn:
                items.append({"section": section, "point": mn.group(1), "text": text})
            elif items:
                items[-1]["text"] += "\n" + text
            else:
                items.append({"section": section, "point": "", "text": text})
        else:
            k = _point_key(label)
            if _LETTER.match(label) and items and items[-1]["point"]:
                items[-1]["text"] += "\n" + text  # lettered sub-point of a numbered heading
            else:
                items.append({"section": section, "point": k, "text": text})

    # 2) pack tiny consecutive items of the same section; split oversized ones
    groups: list[dict] = []
    for it in items:
        g = groups[-1] if groups else None
        if (
            g
            and g["section"] == it["section"]
            and _wc(it["text"]) < TINY
            and all(w < TINY for w in g["sizes"])
            and _wc(g["text"]) + _wc(it["text"]) <= PACK_WORDS
        ):
            g["text"] += "\n" + it["text"]
            g["points"].append(it["point"])
            g["sizes"].append(_wc(it["text"]))
        else:
            groups.append({**it, "points": [it["point"]], "sizes": [_wc(it["text"])]})

    out: list[Chunk] = []
    for g in groups:
        texts = _split_long(g["text"]) if _wc(g["text"]) > MAX_WORDS else [g["text"]]
        last = 0  # top-level point numbers only ever increase inside an annex group
        pts_prev = ""
        for part_i, text in enumerate(texts, 1):
            pts = [p for p in g["points"] if p]
            heads = []
            for h in re.findall(r"^(\d+)\.\s", text, flags=re.MULTILINE):
                if int(h) >= last:  # ignore restarting sub-lists like "1." inside point 4
                    heads.append(h)
                    last = int(h)
            if len(texts) > 1 and not _NUM_HEAD.match(text) and pts_prev:
                heads = [pts_prev] + heads  # continuation of the previous point
            if heads and (len(texts) > 1 or len(heads) > 1):  # numbered lines inside the piece
                pts = [heads[0], heads[-1]] if heads[0] != heads[-1] else [heads[0]]
            pts_prev = pts[-1] if pts else ""
            key = "-".join([pts[0], pts[-1]] if len(pts) > 1 else pts) if pts else "intro"
            cid = "_".join(x for x in [u.id, g["section"], key] if x)
            if len(texts) > 1 and not _NUM_HEAD.match(text):
                cid += f"_p{part_i}"
            out.append(
                Chunk(
                    id=cid, kind="annex", label=_annex_label(u.number, g["section"], pts),
                    text=text, point=pts[0] if pts else "", **base,
                )
            )
    return out


def build_chunks(doc: Document) -> list[Chunk]:
    chunks: list[Chunk] = []

    for u in doc.recitals:
        t = text_of(u.element)
        t = re.sub(r"^\(\d+\)\s*", "", t)
        chunks.append(
            Chunk(
                id=u.id, kind="recital", label=f"Recital {u.number}", text=t,
                header=f"Recital {u.number}", url=f"{ELI_URL}#{u.id}", parent=u.id,
                title=f"Recital {u.number}",
            )
        )

    for u in doc.articles:
        header = _article_header(u)
        base = dict(parent=u.id, article=u.number, title=u.title)
        if u.number == "3":  # definitions
            for label, text in segments(u.element, skip_classes=("eli-title", "oj-ti-art")):
                if label == "text":
                    continue
                k = _point_key(label)
                term = re.search(r"‘([^’]+)’", text)
                chunks.append(
                    Chunk(
                        id=f"art_3_{k}", kind="definition", label=f"Art. 3({k})",
                        text=text, header=header, url=f"{ELI_URL}#{u.id}", point=k,
                        term=term.group(1) if term else "", **base,
                    )
                )
            continue

        paras = paragraphs(u.element)
        if not paras:  # article without numbered paragraphs
            segs = segments(u.element, skip_classes=("eli-title", "oj-ti-art"))
            full = "\n".join(t for _, t in segs)
            if _wc(full) > MAX_WORDS and any(lbl != "text" for lbl, _ in segs):
                for cid, label, k, text in _split_points(segs, f"art_{u.number}", f"Art. {u.number}"):
                    chunks.append(Chunk(id=cid, kind="article", label=label, text=text, header=header,
                                        url=f"{ELI_URL}#{u.id}", point=k, **base))
            else:
                chunks.append(Chunk(id=u.id, kind="article", label=f"Art. {u.number}", text=full,
                                    header=header, url=f"{ELI_URL}#{u.id}", **base))
            continue

        for p, el in paras:
            pid, plabel = f"art_{u.number}_{p}", f"Art. {u.number}({p})"
            anchor = el["id"]
            segs = segments(el)
            full = "\n".join(t for _, t in segs)
            if _wc(full) > MAX_WORDS and any(lbl != "text" for lbl, _ in segs):
                for cid, label, k, text in _split_points(segs, pid, plabel):
                    chunks.append(Chunk(id=cid, kind="article", label=label, text=text, header=header,
                                        url=f"{ELI_URL}#{anchor}", paragraph=p, point=k, **base))
            else:
                chunks.append(Chunk(id=pid, kind="article", label=plabel, text=full, header=header,
                                    url=f"{ELI_URL}#{anchor}", paragraph=p, **base))

    for u in doc.annexes:
        chunks.extend(_annex_chunks(u))

    for c in chunks:
        c.refs = extract_refs(c.text, self_parent=c.parent)
        c.words = _wc(c.text)
    _check_unique(chunks)
    return chunks


def _check_unique(chunks: list[Chunk]) -> None:
    """Fail loudly on duplicate IDs (a chunker regression), never rename silently."""
    seen: set[str] = set()
    dups = [c.id for c in chunks if c.id in seen or seen.add(c.id)]
    if dups:
        raise ValueError(f"duplicate chunk ids: {dups[:10]}")


def save(chunks: list[Chunk], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(asdict(c), ensure_ascii=False) + "\n" for c in chunks)


def load_chunks(path: str | Path) -> list[Chunk]:
    with open(path, encoding="utf-8") as f:
        return [Chunk(**json.loads(line)) for line in f]


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/aiact.html"
    dst = sys.argv[2] if len(sys.argv) > 2 else "data/processed/chunks.jsonl"
    chunks = build_chunks(parse(src))
    save(chunks, dst)
    print(f"{len(chunks)} chunks -> {dst}")
