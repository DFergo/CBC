"""LLM provider compatibility (Sprint 22, port of HRDD Sprint 37).

Provider streams recorded on 2026-10-30 from the Mistral API (mistral-large-4,
reasoning on by default → block-format `content`) and OpenRouter
(qwen/qwen3.8-flash via Alibaba, reasoning in a separate field).
"""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from src.services import connection_registry, llm_capabilities as caps, llm_provider as lp
from src.services.llm_config_store import LLMConfig, SlotConfig, _migrate_disable_thinking

FIXTURES = Path(__file__).parent / "fixtures" / "llm"

MISTRAL = {"id": "t-mistral", "type": "api", "api_flavor": "openai_compatible",
           "api_endpoint": "https://api.mistral.ai/v1", "api_key": "k", "enable": True}
OPENROUTER = {"id": "t-or", "type": "api", "api_flavor": "openai_compatible",
              "api_endpoint": "https://openrouter.ai/api/v1", "api_key": "k", "enable": True}
LMSTUDIO = {"id": "t-lms", "type": "lm_studio", "endpoint": "http://host.docker.internal:1234/v1", "enable": True}
OLLAMA = {"id": "t-oll", "type": "ollama", "endpoint": "http://host.docker.internal:11434", "enable": True}
ANTHROPIC = {"id": "t-an", "type": "api", "api_flavor": "anthropic",
             "api_endpoint": "https://api.anthropic.com/v1", "api_key": "k", "enable": True}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class Provider:
    """Patches httpx.AsyncClient in llm_provider; replays responses, records request bodies."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies: list[dict] = []

    def __enter__(self):
        self._orig = lp.httpx.AsyncClient
        real = self._orig

        def handler(request):
            self.bodies.append(json.loads(request.content))
            status, payload = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
            content = (FIXTURES / payload).read_bytes() if payload.endswith(".sse") else payload.encode()
            return httpx.Response(status, content=content)

        lp.httpx.AsyncClient = lambda *a, **kw: real(
            *a, transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"})
        return self

    def __exit__(self, *a):
        lp.httpx.AsyncClient = self._orig


@pytest.fixture(autouse=True)
def conns():
    reg = connection_registry.connections
    for c in (MISTRAL, OPENROUTER, LMSTUDIO, OLLAMA, ANTHROPIC):
        if not reg.get(c["id"]):
            reg.add(dict(c))
    yield


def _stream(conn, model, reasoning=None, usage=None, messages=None, **slot_kw):
    slot = SlotConfig(connection_id=conn["id"], model=model, reasoning=reasoning, **slot_kw)

    async def go():
        out = []
        async for t in lp.stream_chat_one_slot(slot, messages or [{"role": "user", "content": "hi"}], usage=usage):
            out.append(t)
        return "".join(out)
    return _run(go())


# --- B.1 content normaliser ---

def test_content_text():
    assert lp._content_text("abc") == "abc"
    assert lp._content_text(None) == "" and lp._content_text(3) == ""
    blocks = [{"type": "thinking", "thinking": [{"type": "text", "text": "secret"}]},
              {"type": "text", "text": "Hello"}, {"type": "text", "text": " world"}]
    assert lp._content_text(blocks) == "Hello world"


@pytest.mark.parametrize("fixture", ["mistral_large4_recorded.sse", "openrouter_qwen38flash_recorded.sse",
                                     "mistral_large4_stream.sse"])
def test_block_and_reasoning_streams_yield_only_text(fixture):
    usage: dict = {}
    with Provider([(200, fixture)]):
        text = _stream(MISTRAL, "m", usage=usage)
    assert isinstance(text, str) and text
    assert "user greets" not in text and "need respond" not in text
    assert usage.get("prompt_tokens", 0) > 0


# --- B.2 / B.3 capability rules (verified live 2026-10-30) ---

def test_provider_kinds():
    assert caps.provider_kind(MISTRAL) == "mistral"
    assert caps.provider_kind(OPENROUTER) == "openrouter"
    assert caps.provider_kind(LMSTUDIO) == "openai_compatible"
    assert caps.provider_kind(OLLAMA) == "ollama"
    assert caps.provider_kind(ANTHROPIC) == "anthropic"
    assert caps.provider_kind({**LMSTUDIO, "provider": "openrouter"}) == "openrouter"


def test_mistral_never_gets_rejected_fields():
    with Provider([(200, "mistral_large4_recorded.sse")]) as p:
        _stream(MISTRAL, "mistral-large-4", reasoning="off", num_ctx=8192)
    body = p.bodies[0]
    for forbidden in ("num_ctx", "options", "seed", "reasoning", "chat_template_kwargs", "think"):
        assert forbidden not in body
    assert "reasoning_effort" not in body  # large-4 cannot switch reasoning off


def test_reasoning_mapping_per_provider():
    assert caps.reasoning_mapping("mistral", "mistral-small-latest", "off")[0] == {"reasoning_effort": "none"}
    assert caps.reasoning_mapping("openrouter", "qwen/qwen3.8-flash", "off")[0] == {"reasoning": {"enabled": False}}
    with Provider([(200, "openrouter_qwen38flash_recorded.sse")]) as p:
        _stream(OLLAMA, "qwen3:8b", reasoning="off", num_ctx=16384)
    assert p.bodies[0]["think"] is False and p.bodies[0]["options"] == {"num_ctx": 16384}


def test_lmstudio_off_keeps_stable_system_hint():
    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "x"}]
    with Provider([(200, "openrouter_qwen38flash_recorded.sse")]) as p:
        _stream(LMSTUDIO, "qwen3", reasoning="off", messages=msgs)
        _stream(LMSTUDIO, "qwen3", reasoning="off", messages=msgs)
    assert p.bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert p.bodies[0]["messages"][0] == p.bodies[1]["messages"][0]  # hint is idempotent → cache-safe


def test_blank_params_not_sent():
    with Provider([(200, "mistral_large4_recorded.sse")]) as p:
        _stream(MISTRAL, "mistral-large-4", temperature=None, max_tokens=None)
    assert "temperature" not in p.bodies[0] and "max_tokens" not in p.bodies[0]


def test_rejected_optional_field_dropped_and_retried_once():
    err = '{"message":"reasoning_effort low is not supported for this model"}'
    with Provider([(400, err), (200, "mistral_large4_recorded.sse")]) as p:
        text = _stream(MISTRAL, "mistral-medium-latest", reasoning="low")
    assert text
    assert "reasoning_effort" in p.bodies[0] and "reasoning_effort" not in p.bodies[1]


def test_other_errors_still_raise():
    with Provider([(400, '{"message":"bad model"}')]):
        with pytest.raises(httpx.HTTPStatusError):
            _stream(MISTRAL, "nope")


def test_anthropic_cache_breakpoints_thinking_and_usage():
    usage: dict = {}
    msgs = [{"role": "system", "content": "S" * 50}, {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    with Provider([(200, "anthropic_stream.sse")]) as p:
        text = _stream(ANTHROPIC, "claude-x", usage=usage, messages=msgs, reasoning="medium", temperature=0.5)
    body = p.bodies[0]
    assert text == "Hello"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][-2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in body and body["thinking"]["budget_tokens"] == 8192
    assert usage == {"prompt_tokens": 5040, "cached_tokens": 5000, "completion_tokens": 12}


def test_openrouter_supported_parameters_flag_noops():
    d = caps.describe(OPENROUTER, "mistralai/mistral-large-2512", {"reasoning": "off", "temperature": 0.2},
                      ["max_tokens", "temperature"])
    assert d["controls"]["reasoning"]["status"] == "ignored"
    assert d["controls"]["num_ctx"]["status"] == "ignored"


def test_cache_key_is_a_hash():
    key = lp._cache_key("ABCD-1234")
    assert "ABCD" not in key and key == lp._cache_key("ABCD-1234") and lp._cache_key(None) is None


# --- disable_thinking migration ---

def test_disable_thinking_migrates_to_per_slot_reasoning():
    slot = {"connection_id": "c", "model": "m"}
    on = _migrate_disable_thinking({"inference": dict(slot), "compressor": dict(slot), "disable_thinking": True})
    assert "disable_thinking" not in on and on["inference"]["reasoning"] == "off"
    off = _migrate_disable_thinking({"inference": dict(slot), "disable_thinking": False})
    assert off["inference"]["reasoning"] is None
    cfg = LLMConfig(**_migrate_disable_thinking({"inference": dict(slot), "disable_thinking": True}))
    assert cfg.inference.reasoning == "off"
