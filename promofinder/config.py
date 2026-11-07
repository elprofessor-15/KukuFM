from __future__ import annotations

import os
from pathlib import Path


DEFAULTS = {
    "MODEL_PROVIDER": "groq", "USE_LLM": "true", "GROQ_API_KEY": "",
    "GROQ_BASE_URL": "https://api.groq.com/openai/v1",
    "MODEL_NAME": "openai/gpt-oss-120b", "MODEL_FALLBACK_NAME": "openai/gpt-oss-20b",
    "SECOND_MODEL_NAME": "qwen/qwen3.8-27b", "OPENAI_COMPAT_API_KEY": "",
    "OPENAI_COMPAT_BASE_URL": "", "OPENAI_COMPAT_MODEL": "", "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_MODEL": "", "REQUESTS_PER_MINUTE": "20", "TOKENS_PER_MINUTE": "5000",
    "DAILY_TOKEN_BUDGET": "0", "MAX_RETRIES": "6", "LLM_TEMPERATURE": "0",
    "LLM_MAX_OUTPUT_TOKENS": "4000", "PRICE_INPUT_PER_M": "0", "PRICE_OUTPUT_PER_M": "0",
    "DATA_DIR": "./data", "OUTPUT_DIR": "./outputs", "CACHE_DIR": "./.cache",
    "TOP_N": "30", "MAX_PER_EPISODE": "2", "APP_PASSWORD": "",
    "HOSTED_MAX_LLM_CALLS_PER_SESSION": "80",
}


def load_config(streamlit_secrets: dict | None = None) -> dict[str, str]:
    values = DEFAULTS.copy()
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, value = stripped.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    if streamlit_secrets:
        for key in values:
            secret = streamlit_secrets.get(key)
            if secret is not None:
                values[key] = str(secret)
    values.update({key: value for key, value in os.environ.items() if key in values})
    return values


def api_key_name(provider: str) -> str:
    return {"groq": "GROQ_API_KEY", "openai_compatible": "OPENAI_COMPAT_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY", "mock": ""}.get(provider, "GROQ_API_KEY")


def enabled_provider(config: dict[str, str]) -> str:
    provider = config["MODEL_PROVIDER"].strip()
    key_name = api_key_name(provider)
    if config["USE_LLM"].lower() == "true" and key_name and not config.get(key_name):
        print(f"{key_name} is empty, using heuristics-only mode.")
        return "mock"
    return provider if config["USE_LLM"].lower() == "true" else "mock"
