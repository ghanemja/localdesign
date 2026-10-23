import pytest
from localdesign import llm


def _cfg(base):
    return {"api": "openai", "base_url": base, "api_key": "x", "model": "mock-a", "max_tokens": 100, "temperature": 0.2}


def test_stream_text_and_usage(fake_llm):
    out = "".join(d for d in llm.stream(_cfg(fake_llm), "sys", [{"role": "user", "content": "hi"}]) if isinstance(d, str))
    assert "<!DOCTYPE html>" in out


def test_reasoning_content_yields_status(fake_llm):
    deltas = list(llm.stream(_cfg(fake_llm), "sys", [{"role": "user", "content": "think first please"}]))
    assert {"status": "thinking"} in deltas


def test_length_finish_raises_truncated(fake_llm):
    with pytest.raises(llm.Truncated):
        list(llm.stream(_cfg(fake_llm), "sys", [{"role": "user", "content": "say TRUNCATE"}]))


def test_list_models(fake_llm):
    assert llm.list_models(_cfg(fake_llm)) == ["mock-a", "mock-b"]


def test_unreachable_endpoint_is_llm_error():
    with pytest.raises(llm.LLMError):
        list(llm.stream(_cfg("http://127.0.0.1:9/v1"), "s", [{"role": "user", "content": "x"}]))
