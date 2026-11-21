"""Pipeline behaviour with fake LLMs (no API calls) and the real retriever on local embeddings."""

import json
from functools import lru_cache

import pytest

from app.chat.memory import Memory
from app.chat.pipeline import OUT_OF_SCOPE, ChatService
from app.config import Settings
from app.llm.base import LLM, LLMResult, StreamEvent, Usage
from app.retrieval.search import Retriever


class FakeLLM(LLM):
    def __init__(self, model, replies):
        self.model, self.replies, self.calls = model, list(replies), []

    def _next(self, system, messages):
        self.calls.append(messages)
        self.systems = getattr(self, "systems", []) + [system]
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return r(messages) if callable(r) else r

    def generate(self, system, messages, *, max_tokens, thinking=None, json_schema=None):
        return LLMResult(self._next(system, messages), Usage(self.model, 100, 20), "STOP")

    def stream(self, system, messages, *, max_tokens, thinking=None):
        text = self._next(system, messages)
        for i in range(0, len(text), 7):
            yield StreamEvent(delta=text[i:i + 7])
        yield StreamEvent(result=LLMResult(text, Usage(self.model, 1000, 80), "STOP"))


@lru_cache
def retriever():
    return Retriever(embedder="local")


def guard(label="in", q=None, clar=""):
    return lambda msgs: json.dumps({"standalone_question": q or msgs[-1].content.split("NEW message: ")[-1],
                                    "label": label, "clarification": clar, "reason": "t"})


def service(guard_replies, answer_replies):
    g, a = FakeLLM("gemini-3.5-flash-lite", guard_replies), FakeLLM("gemini-3.8-flash", answer_replies)
    svc = ChatService(retriever(), a, g, Memory(":memory:"), Settings())
    return svc, g, a


def run(svc, sid, msg):
    return list(svc.stream(sid, msg))


def test_prefilter_refuses_without_any_llm_call():
    svc, g, a = service([guard()], ["x"])
    sid = svc.mem.new_session()
    (ev,) = run(svc, sid, "Write a Python function to sort a list")
    assert ev["kind"] == "refusal" and ev["stage"] == "prefilter"
    assert not g.calls and not a.calls


def test_first_turn_off_topic_refused_by_floor_without_llm_call():
    svc, g, a = service([guard()], ["x"])
    sid = svc.mem.new_session()
    (ev,) = run(svc, sid, "Give me a recipe for lasagna")
    assert ev["stage"] == "floor" and ev["text"] == OUT_OF_SCOPE
    assert not g.calls and not a.calls


def test_guard_out_refuses_before_answer_model():
    svc, g, a = service([guard("out")], ["x"])
    sid = svc.mem.new_session()
    (ev,) = run(svc, sid, "What are the GDPR rules on data subject access requests?")
    assert ev["stage"] == "guard" and ev["kind"] == "refusal" and len(g.calls) == 1 and not a.calls


def test_ambiguous_asks_clarification():
    svc, g, a = service([guard("ambiguous", clar="Which system do you mean?")], ["x"])
    sid = svc.mem.new_session()
    (ev,) = run(svc, sid, "Is it allowed under the AI Act to do that with AI?")
    assert ev["kind"] == "clarification" and ev["text"] == "Which system do you mean?" and not a.calls


def test_answer_streams_validates_citations_and_saves_memory():
    ans = "Emotion recognition at work is prohibited [Art. 5(1)(f)], see also [Art. 99(3)]."
    svc, g, a = service([guard()], [ans])
    sid = svc.mem.new_session()
    evs = run(svc, sid, "Can my employer use emotion recognition on staff?")
    assert evs[0]["type"] == "meta" and any(s["id"] == "art_5_1_f" for s in evs[0]["sources"])
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == ans
    done = evs[-1]
    assert done["type"] == "done"
    assert [(c["label"], c["valid"]) for c in done["citations"]] == [("Art. 5(1)(f)", True), ("Art. 99(3)", False)]
    assert "invalid_citation" in done["issues"] and done["cost_usd"] > 0
    h = svc.mem.history(sid)
    assert [m["role"] for m in h] == ["user", "assistant"] and h[1]["cited_ids"] == ["art_5_1_f"]


def test_follow_up_uses_rewrite_history_and_carry_over():
    rewritten = "What are the obligations of deployers of high-risk AI systems?"
    svc, g, a = service([guard(), guard(q=rewritten)],
                        ["Providers must ... [Art. 16]", "Deployers must ... [Art. 26(1)]"])
    sid = svc.mem.new_session()
    run(svc, sid, "What are the obligations of providers of high-risk AI systems?")
    evs = run(svc, sid, "and deployers?")
    assert evs[0]["standalone"] == rewritten
    assert any(s["id"].startswith("art_26") for s in evs[0]["sources"])
    # the guard saw the conversation; the answer model got history + the new question, alternating roles
    assert "providers of high-risk" in g.calls[1][-1].content
    roles = [m.role for m in a.calls[1]]
    assert roles == ["user", "assistant", "user"] and rewritten in a.calls[1][-1].content


def test_code_fences_removed_and_flagged():
    svc, g, a = service([guard()], ["Sure:\n```python\nprint(1)\n```\nArt. 5 bans it [Art. 5(1)(f)]"])
    sid = svc.mem.new_session()
    done = run(svc, sid, "Can my employer use emotion recognition on staff?")[-1]
    assert "```" not in done["text"] and "code_removed" in done["issues"]


def test_ask_retries_once_when_postcheck_fails():
    svc, g, a = service([guard()], ["No citations here.", "Prohibited [Art. 5(1)(f)]."])
    sid = svc.mem.new_session()
    out = svc.ask(sid, "Can my employer use emotion recognition on staff?")
    assert out["retried"] and out["issues"] == [] and len(a.calls) == 2


@pytest.mark.parametrize("bad", ["not json", None])
def test_guard_failure_fails_open(bad):
    svc, g, a = service([bad or "{}"], ["Prohibited [Art. 5(1)(f)]."])
    sid = svc.mem.new_session()
    done = run(svc, sid, "Can my employer use emotion recognition on staff?")[-1]
    assert done["type"] == "done"


def test_retrieve_is_thread_safe():
    """Concurrent requests share one retriever: each must get its own similarity (the floor depends on it)."""
    from concurrent.futures import ThreadPoolExecutor

    r = retriever()
    qs = ["Give me a recipe for lasagna", "Can my employer use emotion recognition on staff?"] * 20
    expected = {q: r.retrieve(q, k=3)[1] for q in set(qs)}
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda q: (q, r.retrieve(q, k=3)[1]), qs))
    assert all(abs(top - expected[q]) < 1e-6 for q, top in got)


# ------------------------------------------------------------------ answer style toggle
ANSWER = "Emotion recognition in the workplace is prohibited [Art. 5(1)(f)]."


@pytest.mark.parametrize("style,marker", [("legal", "Be precise and concise"), ("plain", "plain language")])
def test_style_selects_the_answer_prompt_and_is_recorded(style, marker):
    svc, g, a = service([guard()], [ANSWER])
    sid = svc.mem.new_session()
    evs = list(svc.stream(sid, "Can employers use emotion recognition on their staff?", style))
    assert marker in a.systems[-1]
    assert evs[-1]["type"] == "done" and evs[-1]["style"] == style
    assert svc.mem.history(sid)[-1]["meta"]["style"] == style


def test_styles_share_the_grounding_rules():
    from app.chat.prompts import STYLES, answer_system
    legal, plain = answer_system("legal"), answer_system("plain")
    for rule in ("Use ONLY the numbered excerpts", "Never cite a label", "Never write code", "not legal advice",
                 "later amendments"):
        assert rule in legal and rule in plain
    assert set(STYLES) == {"legal", "plain"}


def test_default_style_is_the_original_prompt():
    from app.chat.prompts import ANSWER_SYSTEM, answer_system
    assert ANSWER_SYSTEM == answer_system() and "Be precise and concise" in ANSWER_SYSTEM


def test_unknown_style_rejected_before_any_call():
    svc, g, a = service([guard()], [ANSWER])
    sid = svc.mem.new_session()
    with pytest.raises(ValueError):
        list(svc.stream(sid, "What is a deployer?", "casual"))
    assert not g.calls and not a.calls


def test_style_can_change_mid_conversation():
    svc, g, a = service([guard()], [ANSWER])
    sid = svc.mem.new_session()
    list(svc.stream(sid, "Can employers use emotion recognition on their staff?", "legal"))
    list(svc.stream(sid, "And what about schools?", "plain"))
    assert "Be precise and concise" in a.systems[0] and "plain language" in a.systems[1]


# ------------------------------------------------------------------ per-step timings (recording only)
def test_timings_cover_the_steps_taken():
    svc, g, a = service([guard()], [ANSWER])
    sid = svc.mem.new_session()
    done = list(svc.stream(sid, "Can employers use emotion recognition on their staff?"))[-1]
    tm = done["timings_ms"]
    assert {"prefilter", "floor", "guard", "retrieve", "answer_first_token", "time_to_first_token", "answer",
            "postcheck"} <= set(tm)
    assert all(v >= 0 for v in tm.values())


def test_prefilter_refusal_times_only_the_prefilter():
    svc, g, a = service([guard()], ["x"])
    sid = svc.mem.new_session()
    (ev,) = list(svc.stream(sid, "Write a Python function to sort a list"))
    assert set(ev["timings_ms"]) == {"prefilter"}


def test_done_event_carries_the_server_verdict_per_bracket_and_saves_it():
    ans = "Prohibited [Art. 5(1)(f), Art. 99(3)]."  # one bracket, two citations joined by a comma
    svc, g, a = service([guard()], [ans])
    sid = svc.mem.new_session()
    done = run(svc, sid, "Can my employer use emotion recognition on staff?")[-1]
    verdict = done["brackets"]["Art. 5(1)(f), Art. 99(3)"]
    assert [(c["label"], c["valid"]) for c in verdict] == [("Art. 5(1)(f)", True), ("Art. 99(3)", False)]
    assert verdict[0]["url"] and not verdict[1]["url"]
    assert svc.mem.history(sid)[1]["meta"]["brackets"] == done["brackets"]  # a reloaded page draws the same marks
