"""Prompt-cache acceptance (Sprint 22, handoff section A).

Drives real chat turns through `polling._process_turn` (prompt assembly,
session store, compression, provider request) against a fake OpenAI-compatible
provider that records every request body, and checks that turn N+1 starts with
exactly the same bytes as turn N — with per-turn RAG and across a compression.
"""
import asyncio
import json

import httpx
import pytest

from src.services import (
    connection_registry, context_compressor, llm_config_store, llm_provider as lp,
    polling, prompt_assembler, rag_service, session_store as ss_mod,
)
from src.services.llm_config_store import LLMConfig, SlotConfig

SUMMARY = "SUMMARY: the user compares overtime clauses."


def _sse(text: str) -> bytes:
    return f'data: {json.dumps({"choices": [{"delta": {"content": text}}]})}\n\ndata: [DONE]\n\n'.encode()


class FakeProvider:
    def __init__(self):
        self.chat_bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "You compress a chat conversation" in body["messages"][0]["content"]:
            return httpx.Response(200, content=_sse(SUMMARY))
        self.chat_bodies.append(body)
        return httpx.Response(200, content=_sse(f"Reply {len(self.chat_bodies)}."))


@pytest.fixture
def env(monkeypatch):
    fake = FakeProvider()
    real = httpx.AsyncClient
    monkeypatch.setattr(lp.httpx, "AsyncClient", lambda *a, **kw: real(
        *a, transport=httpx.MockTransport(fake.handler), **{k: v for k, v in kw.items() if k != "transport"}))

    def fake_rag(**kw):
        q = kw.get("query_text") or ""
        return [rag_service.Chunk(text=f"Art. 7 overtime excerpt for: {q[:30]}", score=0.9,
                                  source="cba_a.pdf", tier="company", scope_key="fe/acme")], \
               [{"tier": "company", "scope_key": "fe/acme"}]
    monkeypatch.setattr(prompt_assembler, "_resolve_rag", fake_rag)
    monkeypatch.setattr(rag_service, "query_tables", lambda *a, **kw: [])
    reg = connection_registry.connections
    if not reg.get("fake"):
        reg.add({"id": "fake", "type": "lm_studio", "endpoint": "http://fake/v1"})
    return fake


def _config(compression_enabled=False):
    slot = SlotConfig(connection_id="fake", model="m")
    cfg = LLMConfig(inference=slot, compressor=slot, summariser=slot, translation=slot)
    cfg.compression.enabled = compression_enabled
    cfg.compression.first_threshold = 1000
    cfg.compression.step_size = 100000
    llm_config_store.save_config(cfg)


class _FE:
    async def post(self, *a, **kw):
        return httpx.Response(200)


def _turns(token: str, texts: list[str]):
    survey = {"company_slug": "acme", "company_display_name": "Acme", "initial_query": texts[0]}
    ss_mod.store.init_session(token=token, system_prompt="", survey=survey, language="en", frontend_id="fe")
    loop = asyncio.new_event_loop()
    for t in texts:
        loop.run_until_complete(polling._process_turn(_FE(), "http://fe", "fe", "fe", token, t, "en"))


def _common_prefix(a, b) -> int:
    n = 0
    for x, y in zip(a, b):
        if json.dumps(x) != json.dumps(y):
            break
        n += 1
    return n


def test_turn_n_plus_1_starts_with_turn_n(env, monkeypatch):
    monkeypatch.setattr(polling, "_push_chunk", lambda *a, **kw: asyncio.sleep(0))
    _config()
    _turns("PREF-CBC1", ["Compare overtime rules.", "And night shifts?", "Which is better for us?"])
    bodies = env.chat_bodies
    assert len(bodies) == 3
    for prev, nxt in zip(bodies, bodies[1:]):
        p, n = prev["messages"], nxt["messages"]
        assert _common_prefix(p, n) == len(p) - 1          # all but this turn's user message
        assert json.dumps(n).startswith(json.dumps(p[:-1])[:-1])  # byte-identical prefix
    last = bodies[-1]["messages"]
    assert "Art. 7 overtime excerpt" not in last[0]["content"]      # RAG not in the system prompt
    assert "Art. 7 overtime excerpt for: Which is better" in last[-1]["content"]


def test_prefix_stable_after_compression(env, monkeypatch):
    monkeypatch.setattr(polling, "_push_chunk", lambda *a, **kw: asyncio.sleep(0))
    _config(compression_enabled=True)
    long = "Please compare the overtime clauses in detail. " * 20
    _turns("PREF-CBC2", [f"Turn {i}: {long}" for i in range(9)])
    with_summary = [b for b in env.chat_bodies if any(SUMMARY in m["content"] for m in b["messages"])]
    assert len(with_summary) >= 2, "compression should happen and its summary be reused"
    for prev, nxt in zip(with_summary, with_summary[1:]):
        assert _common_prefix(prev["messages"], nxt["messages"]) == len(prev["messages"]) - 1
    context_compressor.forget_session("PREF-CBC2")
