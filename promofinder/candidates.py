from __future__ import annotations

import hashlib


def generate_candidates(episode: dict, min_duration: float = 20, max_duration: float = 60) -> list[dict]:
    beats = episode["beats"]
    if not beats:
        return []
    starts = sorted({beat["start"] for beat in beats if beat["kind"] in {"dialogue", "action"}})
    ends = sorted({beat["end"] for beat in beats})
    candidates: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for start in starts:
        for target in range(int(min_duration), int(max_duration) + 1, 2):
            possible = [end for end in ends if start < end and min_duration <= end - start <= max_duration
                        and abs((end - start) - target) <= 2.0]
            if not possible:
                continue
            end = min(possible, key=lambda value: abs(value - start - target))
            key = (round(start * 2), round(end * 2))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(_candidate(episode, start, end))
    for scene in episode["scenes"]:
        valid_ends = [beat["end"] for beat in beats if beat["start"] >= scene["start"]
                      and beat["end"] <= scene["end"]]
        if not valid_ends:
            continue
        end = max(valid_ends)
        valid_starts = [beat["start"] for beat in beats
                        if beat["kind"] in {"dialogue", "action"}
                        and end - min(45, max_duration) <= beat["start"] <= end - min_duration]
        if not valid_starts:
            continue
        start = min(valid_starts)
        if min_duration <= end - start <= max_duration and not any(
                item["segments"][0]["episode"] == episode["number"]
                and abs(item["segments"][0]["start"] - start) < 1 for item in candidates):
            candidates.append(_candidate(episode, start, end, ending=True))
    return candidates


def _candidate(episode: dict, start: float, end: float, ending: bool = False) -> dict:
    segment = {"episode": episode["number"], "start": start, "end": end}
    key = f'{episode["number"]}:{start:.2f}:{end:.2f}'
    return {"id": hashlib.sha1(key.encode()).hexdigest()[:10], "segments": [segment],
            "duration": end - start, "ending_window": ending, "experimental": False}
