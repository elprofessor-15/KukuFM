from __future__ import annotations

from .schemas import ColdViewer, EpisodeJudgments
from .timeutil import parse_time
from .validate import quote_in_interval, quote_verified


def _contains_input_shingle(client, value: str) -> bool:
    check = getattr(client, "_contains_input_shingle", None)
    return bool(check and check(value))


def judge_episode(episode: dict, candidates: list[dict], bible: dict, client,
                  model: str | None = None) -> list[dict]:
    compact = []
    for candidate in candidates[:6]:
        segment = candidate["segments"][0]
        lines = [block for block in episode["blocks"]
                 if segment["start"] <= block["start"] and block["end"] <= segment["end"]
                 and block["kind"] in {"dialogue", "action", "sound"}]
        lines = lines[:14]
        excerpt = " | ".join(
            f'{block["start"]:.2f} {block["kind"]} {block["speaker"] or ""} {block["emotion"] or ""}: '
            f'{block["text"][:100]}' for block in lines)
        compact.append({"candidate_id": candidate["id"], "range": [segment["start"], segment["end"]],
                        "text": excerpt})
    prompt = (
        "Judge short promos for a new viewer. Score hook, cliffhanger, standalone from 1 to 10. "
        "3 means weak, 6 means mixed, 9 means strong and clear from this excerpt. "
        "Quotes must be exact and at most 8 words. Keep why and weakness abstract, do not repeat other script text. "
        "Return only requested JSON. "
        f'Bible: {bible.get("premise", "")[:400]}\nEpisode {episode["number"]}: '
        f'{episode["logline"][:300]}\nNotes: {episode["continuity_notes"][:300]}\n'
        f"Candidates: {compact}"
    )
    output = client.complete_json(prompt, EpisodeJudgments,
                                  system="Use only supplied screenplay evidence. Do not fabricate exact quotes. "
                                  "Do not use em dash or en dash characters.",
                                  model=model)
    by_id = {candidate["id"]: candidate for candidate in candidates[:6]}
    results = []
    for judgment in output.judgments:
        candidate = by_id.get(judgment.candidate_id)
        if not candidate:
            continue
        item = judgment.model_dump()
        if _contains_input_shingle(client, item["why"]):
            item["why"] = "This candidate needs an editor review."
        if _contains_input_shingle(client, item["weakness"]):
            item["weakness"] = "This candidate needs an editor review."
        segment = candidate["segments"][0]
        hook_ok = (quote_verified(item["hook_line"], episode)
                   and quote_in_interval(item["hook_line"], episode, segment["start"], segment["start"] + 3))
        cliffhanger_ok = (
            quote_verified(item["cliffhanger_line"], episode)
            and quote_in_interval(item["cliffhanger_line"], episode, segment["end"] - 4, segment["end"],
                                  use_block_end=True))
        item["quote_verified"] = hook_ok and cliffhanger_ok
        if not item["quote_verified"]:
            features = candidate.get("features", {})
            if not hook_ok:
                item["hook_line"] = " ".join(features.get("hook_line", "").split()[:8])
                item["hook_score"] = max(1, item["hook_score"] - 3)
            if not cliffhanger_ok:
                item["cliffhanger_line"] = " ".join(features.get("cliffhanger_line", "").split()[:8])
                item["cliffhanger_score"] = max(1, item["cliffhanger_score"] - 3)
            item["weakness"] = "unverified quote"
        else:
            for key in ("hook_line", "cliffhanger_line"):
                item[key] = item[key][:140]
        try:
            item["hook_time_seconds"] = parse_time(item["hook_time"])
        except ValueError:
            item["hook_time_seconds"] = candidate["segments"][0]["start"]
        start = segment["start"]
        item["timestamp_verified"] = start <= item["hook_time_seconds"] <= start + 3
        if not item["timestamp_verified"]:
            item["hook_score"] = max(1, item["hook_score"] - 2)
            item["weakness"] = "hook timestamp is outside the opening window"
        for key in ("hook_line", "cliffhanger_line"):
            item[key] = " ".join(item[key].split()[:8])
        results.append({**candidate, **item})
    return results


def cold_viewer(promo: dict, episodes: dict[int, dict], client) -> dict:
    excerpts = []
    for segment in promo["segments"]:
        episode_data = episodes.get(segment["episode"])
        if episode_data:
            excerpts.append(" | ".join(block["text"] for block in episode_data["blocks"]
                                       if segment["start"] <= block["start"] <= segment["end"] and block["text"]))
    excerpt = " | ".join(excerpts)
    output = client.complete_json(
        "A viewer has never seen this story. Based only on the following promo text, identify people, conflict, "
        "confusing details, whether you would keep watching, and what you expect next. Paraphrase, do not quote "
        "the screenplay. Return JSON. Text: "
        + excerpt[:1800], ColdViewer,
        system="Do not use outside context or em dash and en dash characters.")
    result = output.model_dump()
    for field in ("people", "conflict", "confusing", "expect_next"):
        value = result[field]
        if isinstance(value, list):
            result[field] = [item if not _contains_input_shingle(client, item)
                             else "This response needs an editor review." for item in value]
        elif isinstance(value, str) and _contains_input_shingle(client, value):
            result[field] = "This response needs an editor review."
    result["cold_clarity"] = 8 if result["conflict"] and not result["confusing"] else (
        5 if result["conflict"] else 2)
    if not result["conflict"]:
        promo["standalone_score"] = max(1, promo.get("standalone_score", 5) - 2)
    return result
