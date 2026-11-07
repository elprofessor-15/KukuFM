from __future__ import annotations

from .judge import cold_viewer


def judge_top_promos(promos: list[dict], episodes: dict[int, dict], client,
                     limit: int = 15) -> list[dict]:
    for promo in promos[:limit]:
        result = cold_viewer(promo, episodes, client)
        promo["cold_viewer"] = result
        promo["cold_clarity"] = result["cold_clarity"]
        promo["cold_clarity_score"] = result["cold_clarity"]
    for promo in promos[limit:]:
        promo["cold_viewer"] = "not run"
        promo["cold_clarity"] = None
    return promos
