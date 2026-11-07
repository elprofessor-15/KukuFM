from __future__ import annotations

from .candidates import generate_candidates
from .features import extract_features


def estimate_run(episodes: list[dict], cold_limit: int = 15, requests_per_minute: int = 20) -> dict:
    prompt_chars = 0
    for episode in episodes:
        candidates = generate_candidates(episode)
        for candidate in candidates:
            candidate["features"] = extract_features(candidate, episode)
        candidates.sort(key=lambda item: item["features"]["hook"] + item["features"]["cliffhanger"],
                        reverse=True)
        for candidate in candidates[:6]:
            segment = candidate["segments"][0]
            lines = [block for block in episode["blocks"]
                     if segment["start"] <= block["start"] <= segment["end"]
                     and block["kind"] in {"dialogue", "action", "sound"}][:14]
            prompt_chars += sum(len(block["text"][:100]) + 45 for block in lines)
    episode_count = len(episodes)
    calls = episode_count + (1 if episode_count else 0) + min(cold_limit, episode_count)
    tokens = max(0, prompt_chars // 4)
    return {"calls": calls, "estimated_input_tokens": tokens,
            "estimated_minutes": round(calls / max(1, requests_per_minute), 1)}
