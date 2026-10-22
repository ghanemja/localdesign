"""Settings: ~/.localdesign/config.json, env vars, presets. Shared shape with localcode."""
from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path(os.environ.get("LD_HOME", Path.home() / ".localdesign"))
CONFIG_PATH = HOME / "config.json"
PROJECTS_DIR = HOME / "projects"
AUDIT_PATH = HOME / "audit.jsonl"

PRESETS: dict[str, dict] = {
    "ollama":     {"api": "openai", "base_url": "http://localhost:11434/v1", "api_key": "ollama", "model": "qwen2.5-coder:7b"},
    "lmstudio":   {"api": "openai", "base_url": "http://localhost:1234/v1", "api_key": "lm-studio", "model": ""},
    "llamacpp":   {"api": "openai", "base_url": "http://localhost:8080/v1", "api_key": "none", "model": ""},
    "vllm":       {"api": "openai", "base_url": "http://localhost:8000/v1", "api_key": "none", "model": ""},
    "custom":     {"api": "openai", "base_url": "", "api_key": "none", "model": ""},
    "openai":     {"api": "openai", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY", "model": "gpt-5"},
    "openrouter": {"api": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY", "model": "anthropic/claude-sonnet-5"},
    "groq":       {"api": "openai", "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY", "model": "llama-3.3-70b-versatile"},
    "anthropic":  {"api": "anthropic", "base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY", "model": "claude-opus-5"},
}

DEFAULTS = {
    "provider": "ollama",
    "api": "openai",
    "base_url": PRESETS["ollama"]["base_url"],
    "model": PRESETS["ollama"]["model"],
    "api_key": "ollama",
    "variants": 3,
    "temperature": 0.8,
    "max_tokens": 16000,
    "allow_cdn": False,
    "effort": "low",          # Anthropic output_config.effort: low | medium | high
    "audit": True,            # append every model call to ~/.localdesign/audit.jsonl
    "mode": "auto",           # generation engine: auto | html | spec (spec = JSON layout rendered locally; best for small models)
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # env overrides (handy for internal endpoints: LD_BASE_URL=https://llm.corp/v1 LD_MODEL=... LD_API_KEY=...)
    for key, env in (("provider", "LD_PROVIDER"), ("base_url", "LD_BASE_URL"), ("model", "LD_MODEL"), ("api_key", "LD_API_KEY"), ("api", "LD_API")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    p = PRESETS.get(cfg["provider"], {})
    cfg.setdefault("api", p.get("api", "openai"))
    # API key: stored value, else the provider's env var. (Stored keys live in plaintext in config.json — prefer env vars.)
    if not cfg.get("api_key") and p.get("api_key_env"):
        cfg["api_key"] = os.environ.get(p["api_key_env"], "")
    return cfg


def save(cfg: dict):
    HOME.mkdir(parents=True, exist_ok=True)
    keep = {k: v for k, v in cfg.items() if k in DEFAULTS or k == "_custom_base_url"}
    CONFIG_PATH.write_text(json.dumps(keep, indent=2) + "\n")


def apply_preset(cfg: dict, provider: str) -> dict:
    p = PRESETS.get(provider)
    if not p:
        return cfg
    cfg["provider"] = provider
    cfg["api"] = p["api"]
    cfg["base_url"] = p["base_url"] or cfg.get("base_url", "")
    cfg["model"] = p["model"] or cfg.get("model", "")
    cfg["api_key"] = os.environ.get(p["api_key_env"], "") if p.get("api_key_env") else p.get("api_key", "none")
    return cfg


def public(cfg: dict) -> dict:
    """Config safe to send to the browser (key masked)."""
    out = dict(cfg)
    k = out.get("api_key") or ""
    out["api_key_set"] = bool(k)
    out["api_key"] = (k[:4] + "…" + k[-3:]) if len(k) > 10 else ("set" if k else "")
    out["presets"] = {k: {"base_url": v["base_url"], "model": v["model"], "api": v["api"]} for k, v in PRESETS.items()}
    return out
