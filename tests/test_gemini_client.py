"""Regression: concurrent first calls must share one Gemini client (a lost client closes itself on GC)."""

from concurrent.futures import ThreadPoolExecutor

from app.llm import gemini


def test_client_created_once_under_concurrency(monkeypatch):
    made = []

    class FakeClient:
        def __init__(self, **kw):
            import time
            time.sleep(0.01)  # widen the race window
            made.append(self)

    monkeypatch.setattr(gemini.genai, "Client", FakeClient)
    monkeypatch.setattr(gemini, "_client", None)
    with ThreadPoolExecutor(16) as ex:
        got = list(ex.map(lambda _: gemini.client(), range(64)))
    assert len(made) == 1
    assert all(g is made[0] for g in got)
