from __future__ import annotations

import json
from pathlib import Path

from .features import _rules


def score_promo(promo: dict) -> float:
    features = promo["features"]
    weights = _rules()["weights"]
    components = {key: promo.get(f"{key}_score", features.get(key, 5))
                  for key in weights}
    if promo.get("cold_clarity") is None:
        components["cold_clarity"] = 5
    total = sum(components[key] * weight for key, weight in weights.items())
    breakdown = {key: round(value * weights[key], 2) for key, value in components.items()}
    breakdown["spoiler_penalty"] = round(features.get("spoiler_risk", 0) * .2, 2)
    breakdown["context_penalty"] = round(features.get("context_debt", 0) * .6, 2)
    breakdown["resolved_penalty"] = 1.0 if features.get("resolved_soon_after") else 0
    breakdown["quote_penalty"] = 1.5 if promo.get("quote_verified") is False else 0
    total -= sum(breakdown[key] for key in ("spoiler_penalty", "context_penalty",
                                             "resolved_penalty", "quote_penalty"))
    promo["score_breakdown"] = breakdown
    promo["score"] = round(max(0, total), 2)
    promo["rank_reason"] = _rank_reason(promo)
    return promo["score"]


def _rank_reason(promo: dict) -> str:
    breakdown = promo["score_breakdown"]
    penalty_keys = ("spoiler_penalty", "context_penalty", "resolved_penalty",
                    "quote_penalty", "diversity_penalty")
    penalties = round(sum(breakdown.get(key, 0) for key in penalty_keys), 2)
    return (f'Weighted hook {breakdown["hook"]}, cliffhanger {breakdown["cliffhanger"]}, '
            f'standalone {breakdown["standalone"]}, cold clarity {breakdown["cold_clarity"]}; '
            f'penalties total {penalties}. Final score {promo["score"]}.')


def rank_promos(promos: list[dict], max_per_episode: int = 2) -> list[dict]:
    for promo in promos:
        score_promo(promo)
    ordered = sorted(promos, key=lambda item: (item["score"], -item.get("global_rank", 10_000),
                                                item["id"]), reverse=True)
    ranked, per_episode, hook_types, pairs = [], {}, set(), set()
    for promo in ordered:
        episode = promo["segments"][0]["episode"]
        if per_episode.get(episode, 0) >= max_per_episode:
            continue
        kind = promo.get("hook_type", promo["features"].get("hook_type", "mystery"))
        pair = tuple(promo["features"].get("character_pair", []))
        diversity_penalty = 0.0
        if kind in hook_types:
            diversity_penalty += .5
        if pair and pair in pairs and len(ranked) < 15:
            diversity_penalty += .5
        if diversity_penalty:
            promo["score"] = round(max(0, promo["score"] - diversity_penalty), 2)
            promo["score_breakdown"]["diversity_penalty"] = diversity_penalty
            promo["rank_reason"] = _rank_reason(promo)
        per_episode[episode] = per_episode.get(episode, 0) + 1
        hook_types.add(kind)
        if pair:
            pairs.add(pair)
        promo["rank"] = len(ranked) + 1
        promo["post_first"] = promo["rank"] <= 5
        ranked.append(promo)
    return ranked


def rerank_feedback(promos: list[dict], feedback_path: str | Path) -> list[dict]:
    path = Path(feedback_path)
    if not path.exists():
        return rank_promos(promos)
    decisions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for promo in promos:
        kind = promo.get("hook_type", promo["features"]["hook_type"])
        change = sum(.5 if row["decision"] == "accept" else -.5
                     for row in decisions if row.get("decision") in {"accept", "reject"}
                     and row.get("hook_type") == kind)
        change = max(-1.0, min(1.0, change))
        promo["feedback_adjustment"] = round(change, 2)
        promo["score"] = round(max(0, promo.get("score", 0) + change), 2)
        promo["rank_reason"] += f" Feedback adjustment: {change:+.1f} for this hook type."
    promos.sort(key=lambda item: (item["score"], item["id"]), reverse=True)
    for rank, promo in enumerate(promos, 1):
        promo["rank"] = rank
        promo["post_first"] = rank <= 5
    return promos
