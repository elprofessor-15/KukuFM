from __future__ import annotations

import csv
from pathlib import Path


def build_campaign(promos: list[dict], output: str | Path) -> list[dict]:
    plan = []
    remaining = list(promos)
    previous_episode = None
    previous_hook = None
    for index in range(1, 15):
        if not remaining:
            break
        options = [item for item in remaining
                   if item["segments"][0]["episode"] != previous_episode]
        if not options:
            options = remaining[:]
        different_hook = [item for item in options
                          if item.get("hook_type", item["features"]["hook_type"]) != previous_hook]
        if different_hook:
            options = different_hook
        if index <= 5:
            promo = min(options, key=lambda item: (
                item["features"].get("spoiler_risk", 0), -item["score"]))
        elif index >= 11:
            promo = max(options, key=lambda item: (item.get("experimental", False), item["score"]))
        else:
            promo = max(options, key=lambda item: (not item.get("experimental", False), item["score"]))
        remaining.remove(promo)
        episode = promo["segments"][0]["episode"]
        reason = ("Low spoiler risk for an early post." if index <= 5 else
                  "An experimental stitched promo is scheduled later." if promo.get("experimental") else
                  "Changes episode and hook type from the prior slot where possible.")
        plan.append({"day": index, "promo_id": promo["id"], "episode": episode,
                     "hook_type": promo.get("hook_type", promo["features"]["hook_type"]),
                     "reason": reason})
        previous_episode = episode
        previous_hook = promo.get("hook_type", promo["features"]["hook_type"])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "campaign_plan.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["day", "promo_id", "episode", "hook_type", "reason"])
        writer.writeheader()
        writer.writerows(plan)
    (output / "campaign_plan.md").write_text(
        "# Posting plan\n\n" + "\n".join(
            f'Day {slot["day"]}: {slot["promo_id"]}, episode {slot["episode"]}. {slot["reason"]}' for slot in plan),
        encoding="utf-8")
    return plan
