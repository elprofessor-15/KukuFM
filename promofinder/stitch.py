from __future__ import annotations


def validate_stitched(promo: dict, episodes: dict[int, dict]) -> list[str]:
    errors = []
    segments = promo.get("segments", [])
    if not 2 <= len(segments) <= 3:
        errors.append("stitched promos need 2 to 3 segments")
    if any(segment["end"] - segment["start"] < 4 for segment in segments):
        errors.append("each stitched segment must be at least four seconds")
    if sum(segment["end"] - segment["start"] for segment in segments) < 20 or \
            sum(segment["end"] - segment["start"] for segment in segments) > 60:
        errors.append("stitched duration must be 20 to 60 seconds")
    if any(int(segment["episode"]) not in episodes for segment in segments):
        errors.append("stitched segment refers to missing episode")
    for segment in segments:
        episode = episodes.get(int(segment["episode"]))
        if episode and (segment["start"] < 0 or segment["end"] > episode["duration"]
                        or segment["start"] >= segment["end"]):
            errors.append("stitched segment is outside episode duration")
    if promo.get("hook_type") is None or not promo.get("cliffhanger_line"):
        errors.append("stitched promo has no hook or cliffhanger evidence")
    return errors
