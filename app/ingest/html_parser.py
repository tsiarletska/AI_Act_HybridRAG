"""Parse the EUR-Lex HTML of Regulation (EU) 2024/1689 into structural units.

The OJ HTML carries stable anchors which we rely on:
  rct_N        recital N
  cpt_X        chapter X            cpt_X.sct_N   section N of chapter X
  art_N        article N            NNN.PPP       article N, paragraph P
  anx_X        annex X
Points such as (a), (b) or 1., 2. are rendered as two-column tables (label | text),
possibly nested.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

ELI_URL = "https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng"

PARA_ID = re.compile(r"^(\d{3})\.(\d{3})$")
ROMAN = re.compile(r"^[IVXL]+$")


def clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("`", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


# ---------------------------------------------------------------- text rendering
def _is_point_table(t: Tag) -> bool:
    row = t.find("tr")
    return row is not None and len(row.find_all("td", recursive=False)) == 2


def _point_rows(table: Tag) -> list[tuple[str, Tag]]:
    """Return (label, content_cell) for a 2-column point table."""
    out = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) == 2:
            out.append((clean(tds[0].get_text(" ")), tds[1]))
    return out


def render(el: Tag | NavigableString, depth: int = 0) -> str:
    """Render an element to plain text, keeping point labels and line structure."""
    if isinstance(el, NavigableString):
        return str(el)
    if not isinstance(el, Tag):
        return ""
    classes = el.get("class") or []
    # footnote markers like "(1)" in superscript and footnote bodies are dropped
    if "oj-note-tag" in classes or "oj-note" in classes:
        return ""
    if el.name == "sup" or "oj-super" in classes:  # e.g. 10<span class=oj-super>25</span>
        return "^" + el.get_text("")
    if el.name == "table" and _is_point_table(el):
        lines = []
        for label, cell in _point_rows(el):
            body = render_children(cell, depth + 1).strip()
            lines.append("  " * depth + f"{label} {body}")
        return "\n" + "\n".join(lines) + "\n"
    if el.name in ("p", "div", "tr", "li"):
        return "\n" + render_children(el, depth) + "\n"
    return render_children(el, depth)


def render_children(el: Tag, depth: int = 0) -> str:
    return "".join(render(c, depth) for c in el.children)


def text_of(el: Tag) -> str:
    return clean(render(el))


# ---------------------------------------------------------------- data classes
@dataclass
class Unit:
    """A structural unit of the regulation (before chunking)."""

    kind: str  # recital | article | annex
    id: str  # rct_1 | art_5 | anx_III
    number: str  # "1" | "5" | "III"
    title: str = ""
    chapter: str = ""
    chapter_title: str = ""
    section: str = ""
    section_title: str = ""
    element: Tag | None = field(default=None, repr=False)


@dataclass
class Document:
    title: str
    date: str
    recitals: list[Unit]
    articles: list[Unit]
    annexes: list[Unit]


# ---------------------------------------------------------------- parsing
def _title_of(container: Tag) -> str:
    t = container.find(class_="eli-title", recursive=False) or container.find(class_="eli-title")
    return clean(t.get_text(" ")) if t else ""


def _heading_title(container: Tag) -> str:
    """Chapter/section headings look like <p>CHAPTER III</p><div class=eli-title>..."""
    return _title_of(container)


def load(path: str | Path) -> BeautifulSoup:
    return BeautifulSoup(Path(path).read_text(encoding="utf-8"), "lxml")


def parse(path: str | Path) -> Document:
    soup = load(path)
    main_title = soup.find(class_="eli-main-title")
    title = clean(main_title.get_text(" ")) if main_title else "Regulation (EU) 2024/1689"
    hd_date = soup.find(class_="oj-hd-date")
    date = clean(hd_date.get_text()) if hd_date else ""

    recitals = []
    for el in soup.find_all(id=re.compile(r"^rct_\d+$")):
        n = el["id"].split("_")[1]
        recitals.append(Unit("recital", el["id"], n, title=f"Recital {n}", element=el))

    articles = []
    for el in soup.find_all(id=re.compile(r"^art_\d+$")):
        n = el["id"].split("_")[1]
        sti = el.find(class_="oj-sti-art")
        u = Unit("article", el["id"], n, title=clean(sti.get_text(" ")) if sti else "", element=el)
        chap = el.find_parent(id=re.compile(r"^cpt_[IVXL]+$"))
        if chap:
            u.chapter = chap["id"].split("_")[1]
            u.chapter_title = _heading_title(chap)
        sect = el.find_parent(id=re.compile(r"^cpt_[IVXL]+\.sct_\d+$"))
        if sect:
            u.section = sect["id"].split("_")[-1]
            u.section_title = _heading_title(sect)
        articles.append(u)

    annexes = []
    for el in soup.find_all(id=re.compile(r"^anx_[IVXL]+$")):
        n = el["id"].split("_")[1]
        heads = [clean(p.get_text(" ")) for p in el.find_all(class_="oj-doc-ti", limit=2)]
        sub = heads[1] if len(heads) > 1 else ""
        annexes.append(Unit("annex", el["id"], n, title=sub, element=el))

    return Document(title, date, recitals, articles, annexes)


def paragraphs(article: Tag) -> list[tuple[str, Tag]]:
    """Return [(paragraph_number, element)] for an article, [] if not numbered.

    Only anchors whose article part matches this article count: Articles 102-110 amend
    other regulations and quote their paragraphs, which carry the *other* act's ids
    (e.g. '017.003' inside Article 108). Those stay part of the article's own text.
    """
    art_no = int(article["id"].split("_")[1])
    out = []
    for div in article.find_all("div", id=PARA_ID):
        m = PARA_ID.match(div["id"])
        if int(m.group(1)) == art_no:
            out.append((str(int(m.group(2))), div))
    return out


def segments(el: Tag, skip_classes: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Split an element into an ordered, lossless list of segments.

    Each segment is ("text", text) for free text between points, or (label, text)
    for a top-level point such as "(a)" or "1.". Nested sub-points stay inside
    their parent point's text.
    """
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush():
        t = clean("".join(buf))
        if t:
            out.append(("text", t))
        buf.clear()

    for child in el.children:
        if isinstance(child, Tag) and set(child.get("class") or []) & set(skip_classes):
            continue
        if isinstance(child, Tag) and child.name == "table" and _is_point_table(child):
            flush()
            for label, cell in _point_rows(child):
                out.append((label, clean(f"{label} " + render_children(cell, 1).strip())))
        else:
            buf.append(render(child))
    flush()
    return out
