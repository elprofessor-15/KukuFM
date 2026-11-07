import json

import pytest
from pydantic import BaseModel

from promofinder.config import enabled_provider, load_config, model_name
from promofinder.llm import LLMClient, LLMError, _duration_seconds, _parse_json, list_models


def test_config_precedence(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("MODEL_NAME=file-model\nGROQ_API_KEY=file-key\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_NAME", "environment-model")
    config = load_config({"MODEL_NAME": "secret-model", "GROQ_API_KEY": "secret-key",
                          "SECOND_MODEL_NAME": "secret-second"})
    assert config["MODEL_NAME"] == "environment-model"
    assert config["GROQ_API_KEY"] == "file-key"
    assert config["SECOND_MODEL_NAME"] == "secret-second"
    assert model_name(config, "groq") == "environment-model"
    assert model_name(config | {"ANTHROPIC_MODEL": "claude-test"}, "anthropic") == "claude-test"


def test_model_list_flags_non_chat_models(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": name} for name in ("openai/gpt-oss-120b", "whisper-large-v3",
                                                       "prompt-guard-2", "orpheus-english")]}

    monkeypatch.setattr("promofinder.llm.requests.get", lambda *args, **kwargs: Response())
    models = list_models({"MODEL_PROVIDER": "groq", "GROQ_API_KEY": "test-key",
                          "GROQ_BASE_URL": "https://api.groq.test"})
    assert models == [{"id": "openai/gpt-oss-120b", "chat": True},
                      {"id": "whisper-large-v3", "chat": False},
                      {"id": "prompt-guard-2", "chat": False},
                      {"id": "orpheus-english", "chat": False}]


def test_empty_provider_key_disables_live_calls():
    config = {"MODEL_PROVIDER": "groq", "USE_LLM": "true", "GROQ_API_KEY": ""}
    assert enabled_provider(config) == "mock"


def test_openai_compatible_request_uses_configured_api_key():
    class Response:
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    class Session:
        def __init__(self):
            self.headers = None

        def post(self, url, headers, **kwargs):
            self.headers = headers
            return Response()

    session = Session()
    config = load_config() | {
        "MODEL_PROVIDER": "groq",
        "GROQ_API_KEY": "test-key",
        "GROQ_BASE_URL": "https://api.groq.test",
        "CACHE_DIR": "/tmp/promofinder-test-cache",
        "LLM_MAX_OUTPUT_TOKENS": "4000",
    }
    LLMClient(config, session=session)._send("groq", "test-model", "{}", None, True, True)
    assert session.headers["Authorization"] == "Bearer test-key"


def test_parser_extracts_json_from_reasoning_and_prefix():
    assert _parse_json("<think>private thought</think>\n{\"ok\": true}") == {"ok": True}
    assert _parse_json("Here is the result: {\"ok\": true}") == {"ok": True}


def test_invalid_json_is_reported():
    with pytest.raises(LLMError, match="invalid JSON"):
        _parse_json("{broken")


def test_model_response_must_be_object():
    with pytest.raises(LLMError, match="JSON object"):
        _parse_json("no structured result")


def test_rate_header_duration_parsing():
    assert _duration_seconds("1m26.4s") == pytest.approx(86.4)
    assert _duration_seconds("7.725s") == pytest.approx(7.725)
    assert _duration_seconds("1ms") == pytest.approx(.001)


def test_token_rate_limiter_waits_for_rolling_window(monkeypatch, tmp_path):
    clock = {"now": 100.0}
    monkeypatch.setattr("promofinder.llm.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr("promofinder.llm.time.sleep",
                        lambda seconds: clock.__setitem__("now", clock["now"] + seconds))
    config = load_config() | {"CACHE_DIR": str(tmp_path), "REQUESTS_PER_MINUTE": "1000",
                              "TOKENS_PER_MINUTE": "50"}
    client = LLMClient(config)
    client._limit(30)
    client._limit(30)
    assert clock["now"] >= 160
    assert sum(tokens for _, tokens in client.token_window) == 30
