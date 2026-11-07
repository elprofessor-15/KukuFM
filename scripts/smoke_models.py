from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promofinder.candidates import generate_candidates
from promofinder.config import load_config
from promofinder.features import extract_features
from promofinder.judge import judge_episode
from promofinder.llm import LLMClient
from promofinder.parse import parse_episode
from promofinder.preflight import preflight


def main():
    config = load_config()
    episodes = preflight(config["DATA_DIR"])["files_parsed"]
    samples = episodes[:3]
    test_config = config.copy()
    test_config["MODEL_FALLBACK_NAME"] = ""
    client = LLMClient(test_config)
    for episode in samples:
        path = Path(config["DATA_DIR"]) / episode["source"]
        client.protect_text(path.read_text(encoding="utf-8", errors="replace"))
    models = [config["MODEL_NAME"], config["MODEL_FALLBACK_NAME"], config["SECOND_MODEL_NAME"]]
    results = []
    for model in models:
        for episode in samples:
            candidates = generate_candidates(episode)
            for candidate in candidates:
                candidate["features"] = extract_features(candidate, episode)
            candidates.sort(key=lambda item: item["features"]["hook"] + item["features"]["cliffhanger"],
                            reverse=True)
            try:
                judged = judge_episode(episode, candidates[:1], {"premise": ""}, client, model=model)
                item = judged[0] if judged else {}
                quote_ok = item.get("quote_verified", False) and bool(item.get("hook_line")) \
                    and bool(item.get("cliffhanger_line"))
                results.append({"model": model, "episode": episode["number"], "json_valid": bool(judged),
                                "quote_accurate": quote_ok,
                                "timestamp_accurate": item.get("timestamp_verified", False), "error": None})
            except Exception as exc:
                results.append({"model": model, "episode": episode["number"], "json_valid": False,
                                "quote_accurate": False, "timestamp_accurate": False,
                                "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    for model in models:
        rows = [row for row in results if row["model"] == model]
        print(f'{model}: JSON {sum(row["json_valid"] for row in rows)}/{len(rows)}, '
              f'quotes {sum(row["quote_accurate"] for row in rows)}/{len(rows)}, '
              f'timestamps {sum(row["timestamp_accurate"] for row in rows)}/{len(rows)}')
    log = Path("DEV_LOG.md")
    current = log.read_text(encoding="utf-8") if log.exists() else "# Development log\n"
    current = re.sub(r"\n## Model smoke test.*$", "", current, flags=re.S)
    section = "\n## Model smoke test\n\n"
    section += "\n".join(f'- {row["model"]}, episode {row["episode"]}: JSON valid {row["json_valid"]}, '
                        f'quote accurate {row["quote_accurate"]}, timestamp accurate {row["timestamp_accurate"]}.'
                        + (f' Error: {row["error"]}.' if row["error"] else "") for row in results)
    log.write_text(current + section + "\n", encoding="utf-8")
    rates = client.stats["rate_headers"]
    grouped = {}
    for row in rates:
        grouped.setdefault(row["model"], []).append(row["headers"])
    summary = {model: {"request_limit": headers[0].get("x-ratelimit-limit-requests"),
                       "token_limit": headers[0].get("x-ratelimit-limit-tokens"),
                       "retry_after_seconds": [item["retry-after"] for item in headers if "retry-after" in item]}
               for model, headers in grouped.items()}
    log.write_text(log.read_text(encoding="utf-8") + "\nObserved rate limits: "
                   + json.dumps(summary) + "\nObserved 429 messages: "
                   + json.dumps(client.stats["rate_limit_events"]) + "\n", encoding="utf-8")
    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/smoke_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    Path("outputs/smoke_rate_limits.json").write_text(json.dumps({
        "rate_limits": summary, "rate_limit_events": client.stats["rate_limit_events"]}, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    main()
