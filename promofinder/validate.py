from __future__ import annotations

import re


def normalize_quote(text: str) -> str:
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", text).lower()).strip()


def quote_verified(quote: str, episode: dict) -> bool:
    if not quote:
        return True
    normalized = normalize_quote(quote)
    return any(normalized in normalize_quote(block["text"])
               for block in episode.get("blocks", []) if block["text"])


def quote_in_interval(quote: str, episode: dict, start: float, end: float,
                      use_block_end: bool = False) -> bool:
    normalized = normalize_quote(quote)
    if not normalized:
        return False
    for block in episode.get("blocks", []):
        point = block["end"] if use_block_end else block["start"]
        if start <= point <= end and normalized in normalize_quote(block["text"]):
            return True
    return False


def validate_promo(promo: dict, episodes: dict[int, dict]) -> list[str]:
    errors = []
    total = 0.0
    segments = promo.get("segments", [])
    first_segment = segments[0] if segments else None
    last_segment = segments[-1] if segments else None
    for segment in segments:
        episode = episodes.get(int(segment["episode"]))
        if episode is None:
            errors.append("episode not found")
            continue
        start, end = float(segment["start"]), float(segment["end"])
        total += end - start
        if start < 0 or end > episode["duration"]:
            errors.append("segment outside episode duration")
        if start >= end:
            errors.append("segment start must precede end")
    if not 20 <= total <= 60:
        errors.append("promo duration must be 20 to 60 seconds")
    if not promo.get("hook_line"):
        errors.append("hook evidence is missing")
    elif first_segment:
        episode = episodes.get(int(first_segment["episode"]), {})
        if not quote_in_interval(promo["hook_line"], episode, first_segment["start"],
                                 first_segment["start"] + 3):
            errors.append("hook evidence is not in the opening three seconds")
    if not promo.get("cliffhanger_line"):
        errors.append("cliffhanger evidence is missing")
    elif last_segment:
        episode = episodes.get(int(last_segment["episode"]), {})
        if not quote_in_interval(promo["cliffhanger_line"], episode, last_segment["end"] - 4,
                                 last_segment["end"], use_block_end=True):
            errors.append("cliffhanger evidence is not in the final four seconds")
    for key in ("hook_line", "cliffhanger_line"):
        if promo.get(key):
            target_segment = first_segment if key == "hook_line" else last_segment
            if target_segment and not quote_verified(
                    promo[key], episodes.get(int(target_segment["episode"]), {})):
                errors.append(f"{key} is not verified")
    return errors


def overlap_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    intersection = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return intersection / union if union else 0.0
