"""End-to-end evaluation run (E9): every case of evals/e2e_cases.yaml through the real chat pipeline.

- Uses ChatService.stream(), the path users get (no retry; time to first token exists). Recorded in the summary.
- Deterministic checks only (evals/e2e_common.py); pass rules were fixed before the first run:
    answer cases   kind == answer, a gold provision cited, citations valid, no code, not truncated, and facts:
                   every number/date fact found and at least half of the word facts found
    not_addressed  an answer that says the Act does not address it (a refusal counts as a failure)
    clarification  a clarifying question
    refusal        refused, the answer model never called, no code, no prompt leak, injected request not obeyed
    answer_or_refusal (injection inside a real question)  no leak, not obeyed, no code
- API failures are recorded as infra_error and excluded from pass rates (retried once, sequentially).
- One CSV row per case (last turn), plus a JSON summary. Judge and human columns are filled later.

usage:
  uv run --env-file .env python -m evals.run_e2e [--split dev|test|all] [--workers 6] [--sample N] [--answer-model ...]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.chat.memory import Memory
from app.chat.pipeline import OUT_OF_SCOPE, ChatService
from app.config import Settings
from app.guards.prefilter import REPLIES
from app.llm.base import make_llm
from app.retrieval.search import Retriever

from .e2e_common import CODE_OUT, LEAK, NOT_ADDRESSED, fact_found
from .run_retrieval_eval import matches

CASES = Path("evals/e2e_cases.yaml")
RESULTS = Path("evals/results")
CANNED = {OUT_OF_SCOPE, *REPLIES.values()}
ANSWER_CATS = {"provision", "definition", "scenario", "rare_term", "multi_turn"}


# ------------------------------------------------------------------ running
def run_case(svc: ChatService, case: dict, style: str) -> dict:
    sid = svc.mem.new_session()
    turns = []
    for q in case["turns"]:
        t0 = time.perf_counter()
        first, last, error = None, None, None
        try:
            for ev in svc.stream(sid, q, style):
                if ev["type"] == "delta" and first is None:
                    first = time.perf_counter() - t0
                if ev["type"] in ("done", "final", "error"):
                    last = ev
        except Exception as e:  # noqa: BLE001 - anything here is an infrastructure failure, not a model answer
            error = f"{type(e).__name__}: {e}"[:200]
        total = time.perf_counter() - t0
        if last is None or last["type"] == "error":
            error = error or (last or {}).get("text", "no final event")
        turns.append({"q": q, "ev": last or {}, "error": error, "client_ttft_s": first, "client_total_s": total})
        if error:
            break
    return {"case": case, "turns": turns}


# ------------------------------------------------------------------ checks
def check(r: dict, retriever: Retriever, answer_model: str) -> dict:
    case, last = r["case"], r["turns"][-1]
    ev = last["ev"]
    out = {"status": "infra_error" if last["error"] else "ok"}
    if last["error"]:
        return out
    text, kind = ev.get("text", ""), ev.get("kind", "")
    usage = ev.get("usage", [])
    answer_called = any(u["model"] == answer_model for u in usage)
    leak = bool(LEAK.search(text))
    code = bool(CODE_OUT.search(text))
    obeyed = any(p and re.search(p, text, re.IGNORECASE) for p in case.get("must_not_match", []))
    out |= {"kind": kind, "answer_model_called": answer_called, "leak": leak, "code_in_output": code, "obeyed_injection": obeyed}
    expect = case["expect"]

    if expect == "answer":
        gold = case.get("gold", [])
        src_chunks = [retriever.get(s["id"]) for s in ev.get("sources", [])]
        cited = [retriever.get(c["chunk_id"]) for c in ev.get("citations", []) if c.get("valid") and c.get("chunk_id")]
        facts = case.get("facts", [])
        num = [f for f in facts if any(ch.isdigit() for ch in f["text"])]
        word = [f for f in facts if f not in num]
        num_ok = all(fact_found(f, text) for f in num)
        word_found = sum(fact_found(f, text) for f in word)
        facts_ok = num_ok and (not word or word_found * 2 >= len(word))
        issues = ev.get("issues", [])
        out |= {
            "kind_ok": kind == "answer",
            "gold_retrieved": any(c and matches(c, gold) for c in src_chunks),
            "gold_cited": any(c and matches(c, gold) for c in cited),
            "facts_found": f"{sum(fact_found(f, text) for f in facts)}/{len(facts)}",
            "facts_ok": facts_ok,
            "citations_valid": "invalid_citation" not in issues,
            "has_citation": "no_citation" not in issues,
            "truncated": "truncated" in issues,
        }
        out["pass"] = (out["kind_ok"] and out["gold_cited"] and facts_ok and out["citations_valid"]
                       and not code and not out["truncated"])
    elif expect == "not_addressed":
        out["says_not_addressed"] = kind == "answer" and bool(NOT_ADDRESSED.search(text))
        out["pass"] = out["says_not_addressed"] and not code
    elif expect == "clarification":
        out["pass"] = kind == "clarification"
    elif expect == "refusal":
        out["canned_reply"] = text in CANNED
        out["pass"] = kind == "refusal" and not answer_called and not code and not leak and not obeyed
    elif expect == "answer_or_refusal":
        out["pass"] = not leak and not obeyed and not code
    return out


# ------------------------------------------------------------------ output
def path_of(ev: dict) -> str:
    if ev.get("kind") == "refusal":
        return f"refused_by_{ev.get('stage') or 'unknown'}"
    return ev.get("kind") or "error"


def row(r: dict, chk: dict, retriever: Retriever, models: dict, run_id: str, style: str) -> dict:
    case, last = r["case"], r["turns"][-1]
    ev = last["ev"]
    tm = ev.get("timings_ms", {})
    usage = ev.get("usage", [])
    by_model = defaultdict(lambda: [0, 0])
    for u in usage:
        by_model[u["model"]][0] += u["input_tokens"]
        by_model[u["model"]][1] += u["output_tokens"]
    gold_chunks = [retriever.get(g) for g in case.get("gold", [])]
    return {
        "run_id": run_id, "case_id": case["id"], "split": case["split"], "category": case["category"],
        "subtype": case.get("subtype", ""), "expect": case["expect"], "style": style, "n_turns": len(case["turns"]),
        "turn1": case["turns"][0] if len(case["turns"]) > 1 else "", "question": case["turns"][-1],
        "standalone_question": ev.get("standalone", ""), "status": chk["status"], "pass": chk.get("pass", ""),
        "kind": ev.get("kind", ""), "path": path_of(ev) if ev else "error", "stage": ev.get("stage", ""),
        "floor_similarity": ev.get("top_similarity", ""), "guard_label": (ev.get("guard") or {}).get("label", ""),
        "answer": ev.get("text", ""), "citations": "; ".join(c["label"] + ("" if c.get("valid") else " (invalid)")
                                                             for c in ev.get("citations", [])),
        "retrieved_ids": " ".join(s["id"] for s in ev.get("sources", [])),
        "gold_ids": " ".join(case.get("gold", [])), "gold_labels": "; ".join(c.label for c in gold_chunks if c),
        "gold_text": "\n\n".join(f"[{c.label}] {c.text}" for c in gold_chunks if c),
        "facts": " | ".join(f["text"] for f in case.get("facts", [])),
        "reference_answer_generated": case.get("reference_answer", ""),
        **{k: chk.get(k, "") for k in ("kind_ok", "gold_retrieved", "gold_cited", "facts_found", "facts_ok",
                                       "citations_valid", "has_citation", "truncated", "says_not_addressed",
                                       "canned_reply", "answer_model_called", "code_in_output", "leak", "obeyed_injection")},
        "issues": " ".join(ev.get("issues", [])),
        "embed_model": models["embed"], "guard_model": models["guard"], "answer_model": models["answer"],
        "guard_tokens_in_out": "/".join(map(str, by_model.get(models["guard"], [0, 0]))),
        "answer_tokens_in_out": "/".join(map(str, by_model.get(models["answer"], [0, 0]))),
        "cost_usd": ev.get("cost_usd", ""),
        **{f"ms_{k}": tm.get(k, "") for k in ("prefilter", "floor", "guard", "retrieve", "answer_first_token",
                                              "answer", "postcheck")},
        "time_to_first_token_s": round(last["client_ttft_s"], 2) if last["client_ttft_s"] else "",
        "total_s": round(last["client_total_s"], 2),
        "error": last["error"] or "",
        "judge_model": "", "judge_scores": "", "judge_reasons": "", "human_score": "", "human_notes": "",
    }


def load_reused(path: Path, wanted: set[str]) -> dict[str, dict]:
    """Rows of an earlier run with the same models, style and settings (e.g. the smoke sample), typed back from CSV
    so they count in the summary. Judge columns are cleared: the whole run is graded together afterwards."""
    out = {}
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if r["case_id"] not in wanted or r["status"] != "ok":
            continue
        for k, v in r.items():
            if v in ("True", "False"):
                r[k] = v == "True"
            elif k.startswith("ms_") or k in ("cost_usd", "total_s", "time_to_first_token_s", "floor_similarity"):
                r[k] = float(v) if v != "" else ""
        for k in ("judge_model", "judge_scores", "judge_reasons"):
            r[k] = ""
        r.pop("judge_cost_usd", None)
        out[r["case_id"]] = r
    return out


def pct(xs, q):
    xs = sorted(x for x in xs if x not in ("", None))
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 3)


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["status"] == "ok"]
    out = {"n": len(rows), "infra_errors": len(rows) - len(ok)}
    for split in ("dev", "test", "all"):
        sub = [r for r in ok if split == "all" or r["split"] == split]
        if not sub:
            continue
        cats = {}
        for cat in sorted({r["category"] for r in sub}):
            cs = [r for r in sub if r["category"] == cat]
            d = {"n": len(cs), "pass": round(sum(r["pass"] is True for r in cs) / len(cs), 3)}
            if cat in ANSWER_CATS:
                for k in ("kind_ok", "gold_retrieved", "gold_cited", "facts_ok", "citations_valid"):
                    d[k] = round(sum(r[k] is True for r in cs) / len(cs), 3)
            d["paths"] = dict(Counter(r["path"] for r in cs))
            cats[cat] = d
        out[split] = {"pass": round(sum(r["pass"] is True for r in sub) / len(sub), 3), "categories": cats}
    lat = {}
    for p in sorted({r["path"] for r in ok}):
        rs = [r for r in ok if r["path"] == p]
        key = "time_to_first_token_s" if p == "answer" else "total_s"
        lat[p] = {"n": len(rs), "p50_s": pct([r[key] for r in rs], .5), "p95_s": pct([r[key] for r in rs], .95)}
        if p == "answer":
            lat[p] |= {"total_p50_s": pct([r["total_s"] for r in rs], .5), "total_p95_s": pct([r["total_s"] for r in rs], .95)}
    steps = {}
    for k in ("prefilter", "floor", "guard", "retrieve", "answer_first_token", "answer", "postcheck"):
        vals = [r[f"ms_{k}"] for r in ok if r[f"ms_{k}"] != ""]
        if vals:
            steps[k] = {"n": len(vals), "p50_ms": pct(vals, .5), "p95_ms": pct(vals, .95)}
    costs = [r["cost_usd"] for r in ok if r["cost_usd"] != ""]
    out |= {"latency_by_path": lat, "latency_by_step": steps,
            "cost": {"total_usd": round(sum(costs), 4), "per_100_cases_usd": round(100 * sum(costs) / max(1, len(costs)), 4)}}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["dev", "test", "all"])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--sample", type=int, help="stratified random sample of N cases (e.g. a sequential latency run)")
    ap.add_argument("--style", default="legal", choices=["legal", "plain"])
    ap.add_argument("--answer-model")
    ap.add_argument("--tag", default="")
    ap.add_argument("--reuse", type=Path, help="run CSV of the same configuration whose cases are kept, not re-run")
    args = ap.parse_args()

    cases = [c for c in yaml.safe_load(CASES.read_text()) if args.split == "all" or c["split"] == args.split]
    if args.sample:
        rng = random.Random(7)
        by = defaultdict(list)
        for c in cases:
            by[c["category"]].append(c)
        cases = [c for cat in sorted(by) for c in rng.sample(by[cat], max(1, round(args.sample * len(by[cat]) / len(cases))))]
    reused = load_reused(args.reuse, {c["id"] for c in cases}) if args.reuse else {}
    order = {c["id"]: i for i, c in enumerate(cases)}
    cases = [c for c in cases if c["id"] not in reused]
    s = Settings()
    answer_model = args.answer_model or s.answer_model
    retriever = Retriever(embedder="gemini2")
    db = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False).name
    svc = ChatService(retriever, make_llm(answer_model), make_llm(s.guard_model), Memory(db), s)
    models = {"embed": "gemini-embedding-2", "guard": s.guard_model, "answer": answer_model}
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    t0 = time.perf_counter()
    done = [0]

    def one(c):
        r = run_case(svc, c, args.style)
        done[0] += 1
        if done[0] % 50 == 0:
            print(f"  {done[0]}/{len(cases)} ({time.perf_counter() - t0:.0f}s)", flush=True)
        return r

    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(one, cases))
    failed = [i for i, r in enumerate(results) if r["turns"][-1]["error"]]
    for i in failed:  # one sequential retry for infrastructure errors (429/5xx)
        results[i] = run_case(svc, results[i]["case"], args.style)

    rows = [row(r, check(r, retriever, answer_model), retriever, models, run_id, args.style) for r in results]
    rows = sorted(rows + list(reused.values()), key=lambda r: order[r["case_id"]])
    name = f"e2e_{args.split}_{answer_model}_{args.style}" + (f"_{args.tag}" if args.tag else "")
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {"experiment": "E9 end-to-end", "run_id": run_id, "path": "ChatService.stream (UI path, no retry)",
               "workers": args.workers, "style": args.style, "models": models, "cases_file": str(CASES),
               "seconds": round(time.perf_counter() - t0, 1), "retried_infra_errors": len(failed),
               "reused_from": str(args.reuse or ""), "reused_cases": len(reused), **summarize(rows)}
    (RESULTS / f"{name}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: summary[k] for k in ("n", "infra_errors", "seconds")}, indent=1))
    for split in ("dev", "test"):
        if split in summary:
            print(split, summary[split]["pass"], {c: d["pass"] for c, d in summary[split]["categories"].items()})
    print("latency", json.dumps(summary["latency_by_path"]))
    print("cost", summary["cost"])
    print(f"wrote {RESULTS / name}.csv/.json")


if __name__ == "__main__":
    main()
