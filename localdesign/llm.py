"""Streaming text generation over raw HTTP. OpenAI-compatible or Anthropic Messages API. Stdlib only."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterator


class LLMError(Exception):
    pass


class Truncated(LLMError):
    """Raised after the stream ends because the model hit its output token limit."""


def _sse(resp) -> Iterator[dict]:
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


def _post(url, headers, body, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(text).get("error", {})
            msg = msg.get("message", msg) if isinstance(msg, dict) else msg
        except Exception:
            msg = text[:400]
        raise LLMError(f"HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise LLMError(f"Cannot reach {url}: {e.reason}") from None


def _headers(cfg):
    if cfg["api"] == "anthropic":
        return {"x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"}
    h = {"Authorization": f"Bearer {cfg['api_key']}"}
    if "openrouter" in cfg["base_url"]:
        h["X-Title"] = "localdesign"
    return h


def list_models(cfg) -> list[str]:
    base = cfg["base_url"].rstrip("/")
    url = base + ("/v1/models?limit=100" if cfg["api"] == "anthropic" else "/models")
    req = urllib.request.Request(url, headers=_headers(cfg))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code} listing models")
    except urllib.error.URLError as e:
        raise LLMError(f"Cannot reach {base}: {e.reason}")
    return sorted(m.get("id", "") for m in data.get("data", []))


def stream(cfg, system: str, messages: list[dict], temperature: float | None = None) -> Iterator[str]:
    """Yield text deltas (str) or status dicts like {"status": "thinking"}. messages: [{"role", "content"}]"""
    base = cfg["base_url"].rstrip("/")
    temp = cfg.get("temperature", 0.8) if temperature is None else temperature
    if cfg["api"] == "anthropic":
        # Thinking tokens count against max_tokens on current Claude models, so give plenty of room.
        body = {"model": cfg["model"], "max_tokens": max(int(cfg.get("max_tokens") or 8192), 32000), "system": system,
                "messages": messages, "stream": True,
                # Deep reasoning adds minutes of silent latency and doesn't improve mockups; keep it modest.
                "output_config": {"effort": cfg.get("effort") or "medium"}}
        stop = None
        with _post(base + "/v1/messages", _headers(cfg), body) as resp:
            for ev in _sse(resp):
                t = ev.get("type")
                if t == "error":
                    raise LLMError(str(ev.get("error", {}).get("message", ev)))
                if t == "content_block_start" and ev.get("content_block", {}).get("type") == "thinking":
                    yield {"status": "thinking"}
                elif t == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                    yield ev["delta"]["text"]
                elif t == "message_delta":
                    stop = ev.get("delta", {}).get("stop_reason") or stop
        if stop == "max_tokens":
            raise Truncated("Output hit the max_tokens limit; raise Max tokens in Settings.")
        if stop == "refusal":
            raise LLMError("The model declined this request.")
        return
    body = {"model": cfg["model"], "messages": [{"role": "system", "content": system}, *messages], "stream": True,
            "max_tokens": int(cfg.get("max_tokens") or 8192), "temperature": temp}
    finish = None
    try:
        resp = _post(base + "/chat/completions", _headers(cfg), body)
    except LLMError as e:
        msg = str(e).lower()
        if "400" in msg and ("max_tokens" in msg or "max_completion_tokens" in msg or "context length" in msg):
            body.pop("max_tokens", None)   # server has its own cap; let it decide
            resp = _post(base + "/chat/completions", _headers(cfg), body)
        else:
            raise
    with resp:
        for ev in _sse(resp):
            if ev.get("error"):
                raise LLMError(str(ev["error"].get("message", ev["error"])))
            for ch in ev.get("choices", []):
                d = ch.get("delta") or {}
                if d.get("content"):
                    yield d["content"]
                elif d.get("reasoning_content") or d.get("reasoning"):
                    yield {"status": "thinking"}
                finish = ch.get("finish_reason") or finish
    if finish == "length":
        raise Truncated("Output hit the max_tokens limit (or the server's context window); raise Max tokens in Settings or use a model with a larger context.")
