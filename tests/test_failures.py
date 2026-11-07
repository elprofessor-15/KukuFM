import json

import pytest
import requests
from pydantic import BaseModel

from promofinder.config import DEFAULTS, enabled_provider
from promofinder.llm import (AccountKeyUnavailable, BudgetExceeded, LLMClient, LLMError,
                             _parse_json, _safe_provider_message)
from promofinder.validate import quote_verified, validate_promo


class Answer(BaseModel):
    ok: bool


class TextAnswer(BaseModel):
    text: str


@pytest.mark.parametrize("status", [429, 500])
def test_rate_and_server_errors_retry(monkeypatch, status, tmp_path):
    config = DEFAULTS | {"CACHE_DIR": str(tmp_path), "REQUESTS_PER_MINUTE": "1000",
                         "TOKENS_PER_MINUTE": "5000", "MAX_RETRIES": "1"}
    client = LLMClient(config)
    calls = 0

    def send(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            response = requests.Response()
            response.status_code = status
            response._content = b"temporary failure"
            response.headers["retry-after"] = "0"
            raise requests.HTTPError(response=response)
        return '{"ok": true}'

    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr(client, "_limit", lambda tokens: None)
    monkeypatch.setattr(client, "_record", lambda *args: None)
    monkeypatch.setattr("promofinder.llm.time.sleep", lambda delay: None)
    assert client._request("prompt", "groq", "model", None, 10) == '{"ok": true}'
    assert calls == 2
    assert client.stats["retries"] == 1


def test_malformed_and_reasoning_prefixed_json():
    assert _parse_json('<think>text</think>{"ok":true}') == {"ok": True}
    with pytest.raises(LLMError):
        _parse_json("not json")


def test_rate_limit_diagnostic_omits_organization_identifiers():
    message = '{"error":{"message":"Rate limit in organization `org-secret` service tier `private`"}}'
    safe = _safe_provider_message(message)
    assert "org-secret" not in safe
    assert "private" not in safe
    assert "Rate limit" in safe


def test_fabricated_quote_is_rejected():
    episode = {"blocks": [{"text": "The door opens now."}]}
    assert not quote_verified("The king returns tonight.", episode)


def test_timestamp_outside_episode_is_rejected():
    episode = {"number": 1, "duration": 30, "blocks": []}
    promo = {"segments": [{"episode": 1, "start": -1, "end": 25}],
             "hook_line": "", "cliffhanger_line": ""}
    assert "segment outside episode duration" in validate_promo(promo, {1: episode})


def test_empty_api_key_selects_offline_provider(capsys):
    config = {"MODEL_PROVIDER": "groq", "USE_LLM": "true", "GROQ_API_KEY": ""}
    assert enabled_provider(config) == "mock"
    assert "GROQ_API_KEY is empty" in capsys.readouterr().out


def test_daily_budget_stops_additional_calls(tmp_path):
    config = DEFAULTS | {"CACHE_DIR": str(tmp_path), "DAILY_TOKEN_BUDGET": "1"}
    client = LLMClient(config)
    with pytest.raises(BudgetExceeded, match="Daily token budget"):
        client._guard_budget(2)


def test_token_estimate_reserves_input_and_reasoning_output():
    client = LLMClient(DEFAULTS)
    assert client._estimate_tokens("x" * 4000) == 2000


def test_daily_budget_resume_uses_cached_result_after_increase(monkeypatch, tmp_path):
    config = DEFAULTS | {"CACHE_DIR": str(tmp_path), "OUTPUT_DIR": str(tmp_path / "outputs"),
                         "DAILY_TOKEN_BUDGET": "1"}
    client = LLMClient(config)
    with pytest.raises(BudgetExceeded, match="Daily token budget"):
        client.complete_json("prompt", Answer, provider="groq", model="model")
    client.config["DAILY_TOKEN_BUDGET"] = "2000"
    monkeypatch.setattr(client, "_request_with_fallback", lambda *args, **kwargs: '{"ok": true}')
    assert client.complete_json("prompt", Answer, provider="groq", model="model").ok
    client._request_with_fallback = lambda *args: pytest.fail("A cached resume must not call the model")
    assert client.complete_json("prompt", Answer, provider="groq", model="model").ok


def test_empty_length_response_retries_with_larger_output_limit(monkeypatch):
    config = DEFAULTS | {"REQUESTS_PER_MINUTE": "1000", "TOKENS_PER_MINUTE": "5000"}
    client = LLMClient(config)
    attempts = 0

    def send(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise LLMError("Empty content with finish_reason length.")
        return '{"ok": true}'

    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr(client, "_limit", lambda tokens: None)
    assert client._request("prompt", "groq", "model", None, 10) == '{"ok": true}'
    assert attempts == 2
    assert client.config["LLM_MAX_OUTPUT_TOKENS"] == "6000"


def test_json_mode_rejection_retries_without_json_mode(monkeypatch):
    client = LLMClient(DEFAULTS | {"MAX_RETRIES": "1"})
    modes = []

    def send(provider, model, prompt, system, json_mode, reasoning):
        modes.append(json_mode)
        if json_mode:
            response = requests.Response()
            response.status_code = 400
            response._content = b"response_format is unsupported"
            raise requests.HTTPError(response=response)
        return '{"ok": true}'

    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr(client, "_limit", lambda tokens: None)
    assert client._request("prompt", "groq", "model", None, 10) == '{"ok": true}'
    assert modes == [True, False]


def test_fallback_model_is_recorded_after_primary_failure(monkeypatch):
    config = DEFAULTS | {"MODEL_NAME": "primary", "MODEL_FALLBACK_NAME": "fallback"}
    client = LLMClient(config)
    calls = []

    def request(prompt, provider, model, system, token_estimate):
        calls.append(model)
        if model == "primary":
            raise LLMError("temporary failure")
        return '{"ok": true}'

    monkeypatch.setattr(client, "_request", request)
    assert client._request_with_fallback("prompt", "groq", "primary", None, 10) == '{"ok": true}'
    assert calls == ["primary", "fallback"]
    assert client.stats["fallback_events"][0]["to"] == "fallback"


def test_explicit_model_request_does_not_switch_models(monkeypatch, tmp_path):
    config = DEFAULTS | {"CACHE_DIR": str(tmp_path), "OUTPUT_DIR": str(tmp_path / "outputs"),
                         "MODEL_FALLBACK_NAME": "fallback"}
    client = LLMClient(config)
    calls = []

    def request(prompt, provider, model, system, token_estimate):
        calls.append(model)
        raise LLMError("temporary failure")

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "_limit", lambda tokens: None)
    with pytest.raises(LLMError, match="temporary failure"):
        client.complete_json("prompt", Answer, provider="groq", model="qwen/qwen3.8-27b")
    assert calls == ["qwen/qwen3.8-27b"]


def test_daily_provider_limit_stops_without_retry(monkeypatch):
    client = LLMClient(DEFAULTS | {"MAX_RETRIES": "3"})
    response = requests.Response()
    response.status_code = 429
    response._content = b'{"error":{"message":"Daily request quota limit reached"}}'

    def send(*args, **kwargs):
        raise requests.HTTPError(response=response)

    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr(client, "_limit", lambda tokens: None)
    with pytest.raises(BudgetExceeded, match="Provider daily limit"):
        client._request("prompt", "groq", "model", None, 10)
    assert client.stats["retries"] == 0
    assert client.stats["quota_events"]


def test_provider_tokens_per_day_limit_stops_without_fallback(monkeypatch):
    client = LLMClient(DEFAULTS | {"MODEL_FALLBACK_NAME": "fallback", "MAX_RETRIES": "3"})
    response = requests.Response()
    response.status_code = 429
    response._content = (b'{"error":{"message":"Rate limit reached for model `test` on tokens per day '
                         b'(TPD): Limit 200000, Used 196853, Requested 3248"}}')

    def send(*args, **kwargs):
        raise requests.HTTPError(response=response)

    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr(client, "_limit", lambda tokens: None)
    with pytest.raises(BudgetExceeded, match="Provider daily limit"):
        client._request_with_fallback("prompt", "groq", "primary", None, 10)
    assert client.stats["retries"] == 0
    assert client.stats["fallback_events"] == []
    assert client.stats["quota_events"]


def test_daily_limit_switches_to_secondary_groq_key_without_logging_key(monkeypatch):
    config = DEFAULTS | {"GROQ_API_KEY": "primary-private-value",
                         "GROQ_API_KEY2": "secondary-private-value"}
    client = LLMClient(config)
    calls = []

    def request(prompt, provider, model, system, token_estimate):
        calls.append((provider, model, client.active_groq_key))
        if client.active_groq_key == "GROQ_API_KEY":
            raise AccountKeyUnavailable("primary quota")
        return '{"ok": true}'

    monkeypatch.setattr(client, "_request", request)
    response = client._request_with_fallback("prompt", "groq", "openai/gpt-oss-120b", None, 10)
    assert response == '{"ok": true}'
    assert calls == [("groq", "openai/gpt-oss-120b", "GROQ_API_KEY"),
                     ("groq", "openai/gpt-oss-120b", "GROQ_API_KEY2")]
    assert "primary-private-value" not in repr(client.stats)
    assert "secondary-private-value" not in repr(client.stats)
    assert client.stats["api_key_fallback_events"] == [{
        "from": "GROQ_API_KEY", "to": "GROQ_API_KEY2", "reason": "provider daily token limit"}]


def test_secondary_groq_key_can_enable_provider_without_primary(capsys):
    config = {"MODEL_PROVIDER": "groq", "USE_LLM": "true", "GROQ_API_KEY": "",
              "GROQ_API_KEY2": "secondary-private-value"}
    assert enabled_provider(config) == "groq"
    assert capsys.readouterr().out == ""


def test_budget_stop_does_not_switch_models(monkeypatch):
    client = LLMClient(DEFAULTS | {"MODEL_FALLBACK_NAME": "fallback"})

    def request(*args):
        raise BudgetExceeded("Daily token budget reached.")

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(BudgetExceeded):
        client._request_with_fallback("prompt", "groq", "primary", None, 10)
    assert client.stats["fallback_events"] == []


def test_cached_json_returns_without_call(tmp_path):
    prompt, provider, model = "prompt", "groq", "model"
    import hashlib
    schema = Answer.model_json_schema()
    import sys
    key_prompt = prompt + "\nReturn JSON matching this schema exactly: " + json.dumps(
        schema, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256((provider + model + key_prompt).encode()).hexdigest()
    (tmp_path / f"{key}.json").write_text(json.dumps({
        "provider": provider, "model": model, "prompt_hash": key, "response": {"ok": True}}))
    config = DEFAULTS | {"CACHE_DIR": str(tmp_path), "OUTPUT_DIR": str(tmp_path / "outputs")}
    client = LLMClient(config)
    assert client.complete_json(prompt, Answer, provider=provider, model=model).ok
    assert client.stats["calls"] == 0
    assert client.stats["cache_hits"] == 1


def test_response_repeating_screenplay_shingle_is_cached_but_not_exported(tmp_path, monkeypatch):
    text = "the confidential passage stays in memory and is never persisted"
    config = DEFAULTS | {"CACHE_DIR": str(tmp_path / "cache"),
                         "OUTPUT_DIR": str(tmp_path / "outputs")}
    client = LLMClient(config)
    tokens = text.split()
    client.protected_shingles = {tuple(token.lower() for token in tokens[:10])}
    monkeypatch.setattr(client, "_request_with_fallback",
                        lambda *args, **kwargs: json.dumps({"text": text}))
    assert client.complete_json("prompt", TextAnswer, provider="groq", model="model").text == text
    cached = list((tmp_path / "cache").glob("*.json"))
    assert len(cached) == 1
    assert set(json.loads(cached[0].read_text())) == {"provider", "model", "prompt_hash", "response"}
    assert not list((tmp_path / "outputs").rglob("*.json"))
    assert client.stats["unsafe_responses_omitted_from_raw"] == 1
    monkeypatch.setattr(client, "_request_with_fallback",
                        lambda *args, **kwargs: pytest.fail("A cached response must not call the model"))
    assert client.complete_json("prompt", TextAnswer, provider="groq", model="model").text == text


def test_cache_and_raw_output_keep_original_response(tmp_path):
    config = DEFAULTS | {"CACHE_DIR": str(tmp_path / "cache"),
                         "OUTPUT_DIR": str(tmp_path / "outputs")}
    client = LLMClient(config)
    original = '{"ok": true}\n'
    cache_path = tmp_path / "cache" / "response.json"
    client._store_response(cache_path, "groq", "model", "hash", original)
    repeat_client = LLMClient(config | {"CACHE_DIR": str(tmp_path / "repeat_cache")})
    repeat_client._store_response(tmp_path / "repeat_cache" / "response.json",
                                  "groq", "model", "hash", '{"ok": false}')
    cached = json.loads((tmp_path / "cache" / "response.json").read_text())
    raw_files = list((tmp_path / "outputs" / "raw_llm").glob("hash*.json"))
    assert cached["response"] == original
    assert len(raw_files) == 2
    assert {json.loads(path.read_text())["response"] for path in raw_files} == {
        original, '{"ok": false}'}
