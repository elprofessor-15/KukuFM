from __future__ import annotations

from .features import _rules, extract_features
from .rank import score_promo


def suggest_nudge(promo: dict, episodes: dict[int, dict]) -> dict:
    original = promo["segments"][0]
    episode = episodes[original["episode"]]
    edges_start = sorted({beat["start"] for beat in episode["beats"]})
    edges_end = sorted({beat["end"] for beat in episode["beats"]})
    weights = _rules()["weights"]
    start_targets = {round(original["start"] + step * .5, 2) for step in range(-4, 5)}
    end_targets = {round(original["end"] + step * .5, 2) for step in range(-4, 5)}
    best = None
    for start in edges_start:
        if not any(abs(start - target) < .01 for target in start_targets):
            continue
        for end in edges_end:
            if not any(abs(end - target) < .01 for target in end_targets) or not 20 <= end - start <= 60:
                continue
            candidate = {**promo, "segments": [{"episode": original["episode"], "start": start, "end": end}],
                         "duration": end - start}
            candidate["features"] = extract_features(candidate, episode)
            score = (candidate["features"]["hook"] * weights["hook"]
                     + candidate["features"]["cliffhanger"] * weights["cliffhanger"])
            if best is None or score > best["heuristic_score"]:
                best = {**candidate, "heuristic_score": score}
    if best is None:
        return {"changed": False, "reason": "No valid beat edges within two seconds."}
    return {"changed": best["segments"] != promo["segments"], "original": original,
            "suggested": best["segments"][0], "score_delta": round(best["heuristic_score"] -
            (promo["features"]["hook"] * weights["hook"]
             + promo["features"]["cliffhanger"] * weights["cliffhanger"]), 2)}
