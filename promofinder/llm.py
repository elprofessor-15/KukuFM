from __future__ import annotations

import hashlib
import json
import random
import re
import time
import uuid
from pathlib import Path
from typing import Callable
from typing import TypeVar

import requests
from pydantic import BaseModel, ValidationError

from .config import load_config, model_name
from .schemas import Bible, ColdViewer, EpisodeJudgments, GlobalOrder

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    pass


class AccountKeyUnavailable(LLMError):
    pass


def _duration_seconds(value: str) -> float:
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m)", value.lower())
    if not parts:
        try:
            return float(value)
        except ValueError:
            return 0.0
    scale = {"ms": .001, "s": 1.0, "m": 60.0}
    return sum(float(amount) * scale[unit] for amount, unit in parts)


class LLMClient:
    def __init__(self, config: dict[str, str] | None = None, session: object | None = None,
                 session_calls: Callable[[], int] | None = None,
                 record_session_call: Callable[[], None] | None = None):
        self.config = config or load_config()
        self.session = session or requests.Session()
        self.session_calls = session_calls
        self.record_session_call = record_session_call
        self.stats = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cache_hits": 0,
                      "retries": 0, "failures": 0, "estimated_cost": 0.0, "models_used": [],
                      "fallback_events": [], "quota_events": [], "rate_headers": [],
                      "rate_limit_events": [], "api_key_fallback_events": [],
                      "unsafe_responses_omitted_from_raw": 0}
        self.started: list[float] = []
        self.token_window: list[tuple[float, int]] = []
        self.last_call = 0.0
        self.adaptive_delay = 0.0
        self.hosted_calls = 0
        self.protected_shingles: set[tuple[str, ...]] = set()
        self.active_groq_key = ("GROQ_API_KEY" if self.config.get("GROQ_API_KEY")
                                else "GROQ_API_KEY2")

    def protect_text(self, text: str) -> None:
        token_pattern = re.compile(r"\b[\w']+\b", re.UNICODE)
        tokens = [item.lower() for item in token_pattern.findall(text)]
        self.protected_shingles.update(
            tuple(tokens[index:index + 10]) for index in range(max(0, len(tokens) - 9)))

    def _estimate_tokens(self, prompt: str, system: str | None = None) -> int:
        input_estimate = max(1, (len(prompt) + len(system or "")) // 4)
        output_estimate = min(1000, int(self.config.get("LLM_MAX_OUTPUT_TOKENS", "4000")))
        return input_estimate + output_estimate

    def complete_json(self, prompt: str, schema: type[T], system: str | None = None,
                      provider: str | None = None, model: str | None = None) -> T:
        explicit_model = model is not None
        provider = provider or self.config["MODEL_PROVIDER"]
        model = model or model_name(self.config, provider)
        allow_fallback = not explicit_model
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False, sort_keys=True)
        request_prompt = prompt + "\nReturn JSON matching this schema exactly: " + schema_text
        prompt_hash = hashlib.sha256((provider + model + request_prompt + (system or "")).encode()).hexdigest()
        cache_path = Path(self.config["CACHE_DIR"]) / f"{prompt_hash}.json"
        if cache_path.exists():
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_text = saved["response"] if isinstance(saved["response"], str) else json.dumps(
                saved["response"], ensure_ascii=False)
            cached_is_unsafe = self._contains_input_shingle(cached_text)
            self.stats["cache_hits"] += 1
            if cached_is_unsafe:
                self.stats["unsafe_responses_omitted_from_raw"] += 1
            raw_response = saved["response"]
            if isinstance(raw_response, str):
                try:
                    payload = _parse_json(raw_response)
                except LLMError:
                    cache_path.unlink()
                else:
                    result, repaired = self._validate(payload, schema, request_prompt, provider, model, system,
                                                      cache_path, prompt_hash, raw_response, allow_fallback)
                    if self._contains_input_shingle(repaired):
                        if not cached_is_unsafe:
                            self.stats["unsafe_responses_omitted_from_raw"] += 1
                            self._write_cache_response(cache_path, provider, model, prompt_hash, repaired)
                    elif repaired != raw_response:
                        self._store_response(cache_path, provider, model, prompt_hash, repaired)
                    else:
                        self._store_raw_response(provider, model, prompt_hash, raw_response, False)
                    return result
            else:
                raw_response = json.dumps(raw_response, ensure_ascii=False)
                result, repaired = self._validate(saved["response"], schema, request_prompt, provider, model,
                                                  system, cache_path, prompt_hash, raw_response, allow_fallback)
                if self._contains_input_shingle(repaired):
                    if not cached_is_unsafe:
                        self.stats["unsafe_responses_omitted_from_raw"] += 1
                        self._write_cache_response(cache_path, provider, model, prompt_hash, repaired)
                elif repaired != raw_response:
                    self._store_response(cache_path, provider, model, prompt_hash, repaired)
                else:
                    self._store_raw_response(provider, model, prompt_hash, raw_response, False)
                return result
        if provider == "mock":
            self.stats["calls"] += 1
            result = schema.model_validate(_mock_response(prompt, schema), strict=True)
            return result
        token_estimate = self._estimate_tokens(request_prompt, system)
        self._guard_budget(token_estimate)
        response_text = self._request_with_fallback(request_prompt, provider, model, system, token_estimate,
                                                    allow_fallback=allow_fallback)
        parsed = _parse_json(response_text)
        result, response_text = self._validate(parsed, schema, request_prompt, provider, model, system,
                                               cache_path, prompt_hash, response_text, allow_fallback)
        if self._contains_input_shingle(response_text):
            self.stats["unsafe_responses_omitted_from_raw"] += 1
            self._write_cache_response(cache_path, provider, model, prompt_hash, response_text)
        else:
            self._store_response(cache_path, provider, model, prompt_hash, response_text)
        return result

    def _contains_input_shingle(self, response_text: str) -> bool:
        if not self.protected_shingles:
            return False
        try:
            payload = _parse_json(response_text)
        except LLMError:
            payload = response_text

        def strings(value: object, key: str = ""):
            if isinstance(value, dict):
                for child_key, child in value.items():
                    yield from strings(child, child_key)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child, key)
            elif isinstance(value, str):
                yield value

        for value in strings(payload):
            tokens = [item.lower() for item in re.findall(r"\b[\w']+\b", value, re.UNICODE)]
            for index in range(max(0, len(tokens) - 9)):
                if tuple(tokens[index:index + 10]) in self.protected_shingles:
                    return True
        return False

    def _store_response(self, cache_path: Path, provider: str, model: str,
                        prompt_hash: str, response_text: str) -> None:
        self._write_cache_response(cache_path, provider, model, prompt_hash, response_text)
        self._store_raw_response(provider, model, prompt_hash, response_text, True)

    def _write_cache_response(self, cache_path: Path, provider: str, model: str,
                              prompt_hash: str, response_text: str) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"provider": provider, "model": model,
                                         "prompt_hash": prompt_hash, "response": response_text},
                                         ensure_ascii=False, indent=2), encoding="utf-8")

    def _store_raw_response(self, provider: str, model: str, prompt_hash: str,
                             response_text: str, keep_duplicate: bool) -> None:
        raw_dir = Path(self.config["OUTPUT_DIR"]) / "raw_llm"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{prompt_hash}.json"
        if raw_path.exists():
            if not keep_duplicate:
                return
            raw_path = raw_dir / f"{prompt_hash}-{uuid.uuid4().hex[:8]}.json"
        raw_path.write_text(json.dumps({
            "provider": provider, "model": model, "prompt_hash": prompt_hash, "response": response_text},
            ensure_ascii=False, indent=2), encoding="utf-8")

    def _validate(self, payload: object, schema: type[T], prompt: str, provider: str, model: str,
                  system: str | None, cache_path: Path, prompt_hash: str,
                  response_text: str, allow_fallback: bool = True) -> tuple[T, str]:
        try:
            return schema.model_validate(payload, strict=True), response_text
        except ValidationError as exc:
            if cache_path.exists():
                cache_path.unlink()
            repair_prompt = prompt + "\nReturn corrected JSON only. Validation errors: " + str(exc)[:1500]
            response_text = self._request_with_fallback(
                repair_prompt, provider, model, system, self._estimate_tokens(repair_prompt, system),
                allow_fallback=allow_fallback)
            parsed = _parse_json(response_text)
            try:
                result = schema.model_validate(parsed, strict=True)
            except ValidationError as final:
                self.stats["failures"] += 1
                details = ", ".join(
                    f'{ ".".join(str(part) for part in error["loc"])}:{error["type"]}'
                    for error in final.errors())
                raise LLMError(f"JSON validation failed after one repair ({details}).") from final
            return result, response_text

    def _guard_budget(self, tokens: int) -> None:
        budget = int(self.config.get("DAILY_TOKEN_BUDGET", "0"))
        if budget and self.stats["input_tokens"] + self.stats["output_tokens"] + tokens > budget:
            self.stats["quota_events"].append("daily token budget reached")
            raise BudgetExceeded("Daily token budget reached. Resume after the budget resets.")
        used_calls = self.session_calls() if self.session_calls else self.hosted_calls
        if used_calls >= int(self.config.get("HOSTED_MAX_LLM_CALLS_PER_SESSION", "80")):
            self.stats["quota_events"].append("hosted session call limit reached")
            raise BudgetExceeded("Hosted session LLM call limit reached.")

    def _request_with_fallback(self, prompt: str, provider: str, model: str,
                               system: str | None, token_estimate: int,
                               allow_fallback: bool = True) -> str:
        try:
            return self._request(prompt, provider, model, system, token_estimate)
        except AccountKeyUnavailable as exc:
            if provider != "groq" or self.active_groq_key != "GROQ_API_KEY" \
                    or not self.config.get("GROQ_API_KEY2"):
                raise BudgetExceeded("Provider daily limit reached for all configured Groq keys.") from exc
            self.active_groq_key = "GROQ_API_KEY2"
            self.stats["api_key_fallback_events"].append(
                {"from": "GROQ_API_KEY", "to": "GROQ_API_KEY2", "reason": "provider daily token limit"})
            return self._request(prompt, provider, model, system, token_estimate)
        except BudgetExceeded:
            raise
        except LLMError as primary_error:
            fallback = (self.config.get("MODEL_FALLBACK_NAME", "")
                        if provider == "groq" and allow_fallback else "")
            if not fallback or fallback == model:
                raise
            self.stats["fallback_events"].append({"from": model, "to": fallback, "reason": str(primary_error)[:180]})
            try:
                return self._request(prompt, provider, fallback, system, token_estimate)
            except LLMError as fallback_error:
                self.stats["failures"] += 1
                raise LLMError(f"Primary and fallback models failed: {fallback_error}") from fallback_error

    def _request(self, prompt: str, provider: str, model: str,
                 system: str | None, token_estimate: int) -> str:
        retries = int(self.config.get("MAX_RETRIES", "6"))
        for attempt in range(retries + 1):
            self._limit(token_estimate)
            try:
                response = self._send(provider, model, prompt, system, json_mode=True, reasoning=True)
                return response
            except LLMError as exc:
                if "finish_reason length" in str(exc) and attempt < retries:
                    self.stats["retries"] += 1
                    self.config["LLM_MAX_OUTPUT_TOKENS"] = str(
                        min(8000, int(self.config["LLM_MAX_OUTPUT_TOKENS"]) + 2000))
                    continue
                raise
            except requests.HTTPError as exc:
                response = exc.response
                code = response.status_code if response is not None else 0
                message = response.text[:1000] if response is not None else str(exc)
                if response is not None:
                    headers = {key: value for key, value in response.headers.items()
                               if key.lower().startswith("x-ratelimit-") or key.lower() == "retry-after"}
                    self.stats["rate_headers"].append({"model": model, "headers": headers})
                    if code == 429:
                        self.stats["rate_limit_events"].append(
                            {"model": model, "status": code, "message": _safe_provider_message(message),
                             "headers": headers})
                normalized_message = message.lower()
                daily_quota = (
                    "daily" in normalized_message or "per day" in normalized_message or
                    "tokens per day" in normalized_message or '"tpd"' in normalized_message)
                if daily_quota and ("limit" in normalized_message or "quota" in normalized_message
                                    or "rate limit" in normalized_message):
                    self.stats["quota_events"].append(_safe_provider_message(message)[:180])
                    if provider == "groq" and self.active_groq_key == "GROQ_API_KEY" \
                            and self.config.get("GROQ_API_KEY2"):
                        raise AccountKeyUnavailable("Primary Groq key reached its daily token limit.") from exc
                    raise BudgetExceeded("Provider daily limit reached.")
                if code == 400 and attempt < retries:
                    self.stats["retries"] += 1
                    try:
                        return self._send(provider, model, prompt, system, json_mode=False, reasoning=True)
                    except requests.RequestException:
                        try:
                            return self._send(provider, model, prompt, system, json_mode=False, reasoning=False)
                        except requests.RequestException as final:
                            raise LLMError(str(final)) from final
                if code in {429, 500, 502, 503, 504} and attempt < retries:
                    self.stats["retries"] += 1
                    retry_after = response.headers.get("retry-after", "") if response is not None else ""
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = min(60.0, 2 ** attempt) + random.random()
                    time.sleep(delay)
                    continue
                raise LLMError(f"Provider returned HTTP {code}.") from exc
            except requests.RequestException as exc:
                if attempt < retries:
                    self.stats["retries"] += 1
                    time.sleep(min(60.0, 2 ** attempt) + random.random())
                    continue
                raise LLMError(f"Provider request failed: {exc}") from exc
        raise LLMError("Provider retries exhausted.")

    def _send(self, provider: str, model: str, prompt: str, system: str | None,
              json_mode: bool, reasoning: bool) -> str:
        key_name = {"groq": "GROQ_API_KEY", "openai_compatible": "OPENAI_COMPAT_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
        if provider == "groq":
            key_name = self.active_groq_key
        key = self.config.get(key_name or "", "")
        if not key:
            raise LLMError(f"{key_name or 'API key'} is empty")
        self._guard_budget(max(1, (len(prompt) + len(system or "")) // 4))
        self.stats["calls"] += 1
        self.hosted_calls += 1
        if self.record_session_call:
            self.record_session_call()
        self.stats["models_used"].append(model)
        if provider == "anthropic":
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            body = {"model": model, "max_tokens": int(self.config["LLM_MAX_OUTPUT_TOKENS"]),
                    "temperature": float(self.config["LLM_TEMPERATURE"]),
                    "system": system or "Return valid JSON only.", "messages": [{"role": "user", "content": prompt}]}
            response = self.session.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=90)
            response.raise_for_status()
            data = response.json()
            self._record(response, max(1, len(prompt) // 4), model)
            return "".join(part.get("text", "") for part in data.get("content", []))
        base = self.config["GROQ_BASE_URL"] if provider == "groq" else self.config["OPENAI_COMPAT_BASE_URL"]
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": model, "messages": messages,
                "temperature": float(self.config["LLM_TEMPERATURE"]),
                "max_tokens": int(self.config["LLM_MAX_OUTPUT_TOKENS"])}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if reasoning:
            body["reasoning_effort"] = "low"
        response = self.session.post(base.rstrip("/") + "/chat/completions",
                                     headers=headers, json=body, timeout=120)
        response.raise_for_status()
        data = response.json()
        self._record(response, max(1, (len(prompt) + len(system or "")) // 4), model)
        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content") or ""
        if not content and choice.get("finish_reason") == "length":
            raise LLMError("Empty content with finish_reason length. Increase output limit and retry.")
        return content

    def _usage(self, data: dict, model: str) -> None:
        usage = data.get("usage", {})
        self.stats["input_tokens"] += int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
        self.stats["output_tokens"] += int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
        self.stats["estimated_cost"] = (
            self.stats["input_tokens"] * float(self.config["PRICE_INPUT_PER_M"]) / 1_000_000 +
            self.stats["output_tokens"] * float(self.config["PRICE_OUTPUT_PER_M"]) / 1_000_000)

    def _record(self, response: requests.Response, estimate: int, model: str) -> None:
        data = response.json()
        input_before = self.stats["input_tokens"]
        output_before = self.stats["output_tokens"]
        self._usage(data, model)
        observed_tokens = (self.stats["input_tokens"] - input_before
                           + self.stats["output_tokens"] - output_before)
        if not data.get("usage"):
            self.stats["input_tokens"] += estimate
            estimated_output = max(1, len(data.get("choices", [{}])[0]
                                         .get("message", {}).get("content", "") or "") // 4)
            self.stats["output_tokens"] += estimated_output
            observed_tokens = estimate + estimated_output
        if self.token_window:
            stamp, reserved = self.token_window[-1]
            self.token_window[-1] = (stamp, max(reserved, observed_tokens))
        headers = response.headers
        values = {key: value for key, value in headers.items()
                  if key.lower().startswith("x-ratelimit-") or key.lower() == "retry-after"}
        if values:
            self.stats["rate_headers"].append({"model": model, "headers": values})
        remaining = headers.get("x-ratelimit-remaining-tokens")
        limit = headers.get("x-ratelimit-limit-tokens")
        if remaining and limit and remaining.isdigit() and limit.isdigit() and int(remaining) < int(limit) * .2:
            self.adaptive_delay = max(self.adaptive_delay, _duration_seconds(
                headers.get("x-ratelimit-reset-tokens", "")))
        self.last_call = time.monotonic()

    def _limit(self, estimated_tokens: int) -> None:
        rpm = max(1, int(self.config["REQUESTS_PER_MINUTE"]))
        tpm = max(1, int(self.config["TOKENS_PER_MINUTE"]))
        if estimated_tokens > tpm:
            raise BudgetExceeded("Estimated prompt exceeds TOKENS_PER_MINUTE.")
        if self.adaptive_delay:
            time.sleep(self.adaptive_delay)
            self.adaptive_delay = 0
        while True:
            now = time.monotonic()
            self.started = [stamp for stamp in self.started if now - stamp < 60]
            self.token_window = [(stamp, tokens) for stamp, tokens in self.token_window if now - stamp < 60]
            wait = 0.0
            if len(self.started) >= rpm:
                wait = max(wait, 60 - (now - self.started[0]))
            used_tokens = sum(tokens for _, tokens in self.token_window)
            if used_tokens + estimated_tokens > tpm and self.token_window:
                wait = max(wait, 60 - (now - self.token_window[0][0]))
            if wait <= 0:
                break
            time.sleep(wait)
        if self.last_call:
            time.sleep(max(0, 60 / rpm - (time.monotonic() - self.last_call)))
        stamp = time.monotonic()
        self.started.append(stamp)
        self.token_window.append((stamp, estimated_tokens))


def _parse_json(text: str) -> object:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
    cleaned = re.sub(r"^(?:analysis|reasoning)\s*:\s*.*?(?=\{)", "", cleaned, flags=re.I | re.S).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            raise LLMError("Response did not contain a JSON object.")
        decoder = json.JSONDecoder()
        try:
            result, _ = decoder.raw_decode(cleaned[start:])
            return result
        except json.JSONDecodeError as exc:
            raise LLMError("Response contained invalid JSON.") from exc


def _safe_provider_message(message: str) -> str:
    message = re.sub(r"\s+in organization `[^`]+`", "", message, flags=re.I)
    message = re.sub(r"\s+service tier `[^`]+`", "", message, flags=re.I)
    return message[:400]


def _mock_response(prompt: str, schema: type[BaseModel]) -> dict:
    if schema is Bible:
        return {"premise": "", "characters": {}, "relationships": [], "reveals": []}
    if schema is EpisodeJudgments:
        ids = re.findall(r"'candidate_id': '([^']+)'", prompt)
        if not ids:
            ids = re.findall(r'"candidate_id"\s*:\s*"([^"]+)"', prompt)
        return {"judgments": [
            {"candidate_id": item, "hook_score": 5, "cliffhanger_score": 5, "standalone_score": 5,
             "hook_line": "", "hook_time": "00:00.00", "cliffhanger_line": "",
             "hook_type": "mystery", "why": "Deterministic offline mock score.",
             "weakness": "Mock output is not a real model judgment."} for item in ids]}
    if schema is ColdViewer:
        return {"people": [], "conflict": "", "confusing": ["Mock response is not a viewer test."],
                "keep_watching": False, "expect_next": ""}
    if schema is GlobalOrder:
        return {"order": [], "stitched": []}
    raise LLMError(f"No deterministic mock response is defined for {schema.__name__}.")


def list_models(config: dict[str, str] | None = None) -> list[dict]:
    cfg = config or load_config()
    provider = cfg["MODEL_PROVIDER"]
    if provider == "anthropic":
        key = cfg.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is empty.")
        response = requests.get("https://api.anthropic.com/v1/models",
                               headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                               timeout=30)
        response.raise_for_status()
        return [{"id": item["id"], "chat": True} for item in response.json().get("data", [])]
    key = (cfg.get("GROQ_API_KEY") or cfg.get("GROQ_API_KEY2", "")
           if provider == "groq" else cfg.get("OPENAI_COMPAT_API_KEY", ""))
    if not key:
        raise LLMError("Provider API key is empty.")
    base = cfg["GROQ_BASE_URL"] if provider == "groq" else cfg["OPENAI_COMPAT_BASE_URL"]
    response = requests.get(base.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    response.raise_for_status()
    models = response.json().get("data", [])
    return [{"id": item["id"], "chat": not any(flag in item["id"].lower()
             for flag in ("guard", "safeguard", "whisper", "orpheus"))} for item in models]
