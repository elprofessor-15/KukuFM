from __future__ import annotations

import re
from pathlib import Path
from functools import lru_cache

import yaml


@lru_cache(maxsize=1)
def _rules() -> dict:
    return yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))["features"]


def _short_quote(value: str) -> str:
    text = " ".join(value.split()[:8])
    return text.replace(chr(0x2013), ",").replace(chr(0x2014), ",")


def extract_features(candidate: dict, episode: dict, config: dict | None = None,
                     bible: dict | None = None, first_mentions: dict[str, int] | None = None) -> dict:
    rules = config or _rules()
    segment = candidate["segments"][0]
    start, end = segment["start"], segment["end"]
    blocks = [block for block in episode["blocks"] if start <= block["start"] and block["end"] <= end]
    opening = [block for block in blocks if block["start"] <= start + 3]
    closing = [block for block in blocks if block["end"] >= end - 4]
    text = " ".join(block["text"] for block in blocks).lower()
    hook_text = " ".join(block["text"] for block in opening).lower()
    close_text = " ".join(block["text"] for block in closing).lower()
    words = re.findall(r"\b[\w']+\b", text)
    window_text = " ".join(block["text"] + " " + (block["speaker"] or "") for block in blocks).lower()
    hook_keywords = [word for word in rules.get("hook_keywords", []) if word in hook_text]
    opening_lines = [b for b in opening if b["kind"] == "dialogue" and b["text"]]
    hook_evidence = next((block for block in opening if block["text"]), None)
    first_opening = next((block for block in opening if block["kind"] in {"dialogue", "action"}), None)
    reactive_openers = rules.get("reactive_openers", [])
    reactive_opening = bool(first_opening) and any(
        re.match(r"\b" + re.escape(word) + r"\b", first_opening["text"].lower())
        for word in reactive_openers)
    opening_has_setup = bool(first_opening) and any(
        block is not first_opening and block["kind"] in {"dialogue", "action"} for block in opening)
    hook = min(10, 2 + len(hook_keywords) * 1.4 + (2 if any(p in hook_text for p in ("?", "!", "slap", "strikes")) else 0)
              + (1.2 if any(b["emotion"] for b in opening_lines) else 0)
              + (1.5 if any(b["kind"] == "action" for b in opening) else 0))
    if not opening_lines and not any(b["kind"] == "action" for b in opening):
        hook = 2.5
    if reactive_opening and not opening_has_setup:
        hook = max(1, hook - 1.5)
    cliff = 3 + min(3, sum(mark in close_text for mark in ("?", "!", "...", "…")))
    if any(word in close_text for word in ("threat", "arrives", "reveals", "cut to black", "sting", "ominous")):
        cliff += 2
    if any(word in close_text for word in rules.get("closure_words", [])):
        cliff -= 2
    cliff = max(1, min(10, cliff))
    dialogue_words = sum(len(re.findall(r"\b[\w']+\b", block["text"])) for block in blocks if block["kind"] == "dialogue")
    density = dialogue_words / max(1, candidate["duration"])
    speakers = sorted({block["speaker"] for block in blocks if block["speaker"]})
    emotions = {block["emotion"] for block in blocks if block["emotion"]}
    logline_words = {word for word in re.findall(r"\b[\w']{4,}\b", episode["logline"].lower())}
    central_conflict = bool(logline_words.intersection(set(words)))
    context_debt = 0
    for canonical, aliases in (bible or {}).get("characters", {}).items():
        variants = [canonical, *aliases]
        introduced = min((first_mentions or {}).get(alias.lower(), episode["number"]) for alias in variants)
        if introduced < episode["number"] and any(re.search(
                r"\b" + re.escape(alias.lower()) + r"\b", window_text) for alias in variants):
            context_debt += 1
    resolved = any(word in " ".join(b["text"].lower() for b in episode["blocks"]
                                     if end < b["start"] <= end + 10)
                   for word in ("forgive", "safe now", "it's over", "we are done"))
    hook_type = "mystery"
    for kind, terms in {
        "slap or violence": ("slap", "hit", "strikes", "punch"),
        "reveal": ("secret", "truth", "reveals", "is your"),
        "threat": ("kill", "destroy", "threat", "you will pay"),
        "humiliation": ("kneel", "humiliate", "shame", "publicly"),
        "romantic tension": ("kiss", "love", "marry", "desire"),
        "confrontation": ("accuse", "betray", "why did you", "how could"),
        "shocking line": ("pregnant", "poison", "heir", "divorce"),
    }.items():
        if any(term in hook_text for term in terms):
            hook_type = kind
            break
    spoiler_risk = 0.0
    for reveal in (bible or {}).get("reveals", []):
        try:
            reveal_episode = int(reveal.get("episode", 0))
        except (TypeError, ValueError):
            continue
        reveal_text = str(reveal.get("reveal", reveal.get("description", ""))).lower()
        reveal_terms = {word for word in re.findall(r"\b\w{5,}\b", reveal_text)}
        if reveal_episode and episode["number"] >= reveal_episode and reveal_terms.intersection(set(words)):
            spoiler_risk = min(5.0, spoiler_risk + 1.0)
    standalone = max(1.0, (7.5 if len(speakers) >= 2 else 5.0) - context_debt * .75)
    if central_conflict:
        standalone = min(10, standalone + 1)
    features = {"hook": round(hook, 2), "cliffhanger": round(cliff, 2),
                "standalone": round(standalone, 2),
                "density": round(density, 3), "speaker_count": len(speakers),
                "emotion_shifts": len(emotions), "central_conflict": central_conflict,
                "speakers": speakers,
                "character_pair": speakers[:2] if len(speakers) >= 2 else speakers,
                "reactive_opening": reactive_opening and not opening_has_setup,
                "hook_type": hook_type, "resolved_soon_after": resolved,
                "context_debt": context_debt, "spoiler_risk": spoiler_risk,
                "hook_line": _short_quote(opening_lines[0]["text"] if opening_lines else
                                          hook_evidence["text"] if hook_evidence else ""),
                "cliffhanger_line": _short_quote(next((b["text"] for b in reversed(closing) if b["text"]), "")),
                "why": f'{len(speakers)} speakers and {dialogue_words} dialogue words in {candidate["duration"]:.1f} seconds.'}
    return features
