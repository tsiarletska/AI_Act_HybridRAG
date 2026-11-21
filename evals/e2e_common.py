"""Shared, deterministic pieces of the end-to-end evaluation: text normalisation, fact matching and the
fixed patterns for code and system-prompt leaks. Used by the dataset builder (to validate gold facts
against their source chunk) and by the runner (to check answers) so both apply exactly the same rules."""

from __future__ import annotations

import re

_MONTHS = "January February March April May June July August September October November December".split()

# Digit-group separators: "35 000 000", "35,000,000", "35.000.000" -> "35000000"; "7 %" -> "7%".
_SEP = re.compile(r"(?<=\d)[ ,.  ](?=\d{3}(?:\D|$))")


def normalize(text: str) -> str:
    t = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-").replace(" ", " ").replace(" ", " ")
    prev = None
    while prev != t:  # repeated: each pass removes one separator per digit group
        prev, t = t, _SEP.sub("", t)
    t = re.sub(r"(\d)\s+%", r"\1%", t)
    t = re.sub(r"\bper\s?cent\b", "%", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip()


def _variants(fact: str) -> list[str]:
    """Equivalent surface forms of one fact (numbers in millions, US date order)."""
    f = normalize(fact)
    out = [f]
    m = re.fullmatch(r"(?:EUR |€ ?)?(\d+)(?: ?EUR| ?€| euros?)?", f, flags=re.IGNORECASE)
    if m:  # an amount: the bare number counts, whatever the currency word and its position
        out.append(m.group(1))
        if m.group(1).endswith("000000") and len(m.group(1)) > 6:
            out += [f"{m.group(1)[:-6]} million", f"{m.group(1)[:-6]}m"]
    m = re.fullmatch(r"(\d{1,2}) (%s) (\d{4})" % "|".join(_MONTHS), f)
    if m:
        out.append(f"{m.group(2)} {m.group(1)}, {m.group(3)}")
    return out


def fact_pattern(fact: dict) -> re.Pattern:
    """A fact is {"text": verbatim phrase, "alternatives": [...]}: any variant may appear (case-insensitive,
    flexible whitespace, numbers normalised)."""
    forms = []
    for s in [fact["text"], *fact.get("alternatives", [])]:
        for v in _variants(s):
            esc = re.escape(v).replace(r"\ ", r"\s+")
            forms.append(esc)
    return re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(sorted(set(forms), key=len, reverse=True)), re.IGNORECASE)


def fact_found(fact: dict, text: str) -> bool:
    return bool(fact_pattern(fact).search(normalize(text)))


def fact_in_source(fact: dict, chunk_text: str) -> bool:
    """Gold validation: the fact's own text (not its alternatives) must occur in the source chunk."""
    return bool(fact_pattern({"text": fact["text"]}).search(normalize(chunk_text)))


# Output that is code, whatever the path that produced it.
CODE_OUT = re.compile(r"```|^\s*(?:def |class \w+[:(]|import \w|from \w+ import |#include|public static void|function \w+\()",
                      re.MULTILINE)

# Fragments that only appear in the system prompts: if any shows up in a reply, the prompt leaked.
LEAK = re.compile(
    r"numbered excerpts|input gate of a question-answering|standalone_question|Use ONLY the numbered|"
    r"Never cite a label that is not among|Rules:\s*1\.|You are the input gate",
    re.IGNORECASE,
)

NOT_ADDRESSED = re.compile(
    r"do(?:es)? not (?:address|cover|regulate|mention|contain|specify|set out|deal with)|"
    r"(?:is|are) not (?:addressed|covered|mentioned|regulated)|no (?:provision|rule)s? (?:on|about|for|addressing)|"
    r"not among the provided|provided (?:provisions|excerpts) do not",
    re.IGNORECASE,
)

STOP = set("""a an the of to in on for and or by with as at from that this these those is are be been was were it its which
what who whom when where how does do did can could shall should would will may might must not no any all under into than
then there their them they i we you me my our your about please tell explain if so such also other only own same very
just more most some each per has have had being get got make made use used using""".split())


def content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in STOP]


def longest_shared_run(a: str, b: str) -> int:
    """Longest run of consecutive words shared by a and b (lexical-leakage check)."""
    aw, bw = re.findall(r"\w+", a.lower()), re.findall(r"\w+", b.lower())
    grams = set()
    best = 0
    for n in range(1, 12):
        grams = {tuple(bw[i:i + n]) for i in range(len(bw) - n + 1)}
        if any(tuple(aw[i:i + n]) in grams for i in range(len(aw) - n + 1)):
            best = n
        else:
            break
    return best
