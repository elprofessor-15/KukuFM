from __future__ import annotations

import re
from pathlib import Path

from .timeutil import parse_time

_EPISODE = re.compile(r"EPISODE NUMBER\s*:\s*(?:Episode\s*)?(\d+)", re.I)
_HEADER = re.compile(r"^\s*\*\*([^*]+):\*\*\s*(.*)$")
_TIMES = re.compile(r"Start\s*:\s*\(?\s*([^\s)]+)\s*\)?\s*\|\s*End\s*:\s*\(?\s*([^\s)]+)\s*\)?", re.I)
_SCENE = re.compile(r"^\s*SCENE\s+\d+\s*$", re.I)
_SCENE_START = re.compile(r"Scene start\s*:\s*(.+)", re.I)
_SCENE_END = re.compile(r"Scene end\s*:\s*(.+)", re.I)
_SPEAKER = re.compile(r"\*\*([^*]+):\*\*")
_EMOTION = re.compile(r"^\s*(.*?)\s*\(([^()]*)\)\s*$")


def _kind(raw: str) -> str:
    tag = raw.strip().upper()
    if "CAMERA" in tag:
        return "camera"
    if "ACTION" in tag:
        return "action"
    if "SOUND" in tag:
        return "sound"
    return "dialogue"


def _speaker(label: str) -> tuple[str | None, str | None, str]:
    cleaned = re.sub(r"\s+", " ", label.strip())
    match = _EMOTION.match(cleaned)
    base, emotion = (match.group(1), match.group(2).strip()) if match else (cleaned, None)
    if _kind(base) != "dialogue":
        return None, None, base
    canonical = re.sub(r"\s*\([^)]*\)", "", base.upper())
    canonical = re.sub(r"^(THE|A|AN)\s+", "", canonical)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    canonical = re.sub(r"\b(FORMER|LATE|YOUNG|OLD)\b\s*", "", canonical).strip()
    return canonical, emotion, base


def parse_episode(path: str | Path) -> dict:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    number_match = _EPISODE.search(text)
    if not number_match:
        number_match = re.search(r"episode[-_ ]?(\d+)", path.name, re.I)
    if not number_match:
        raise ValueError("Missing episode number")
    number = int(number_match.group(1))
    logline_match = re.search(r"EPISODE LOGLINE\s*:\s*(.*)", text, re.I)
    notes_match = re.search(r"CONTINUITY NOTES\s*:\s*(.*?)(?=--- SCRIPT START ---)", text, re.I | re.S)
    script = text.split("--- SCRIPT START ---", 1)[-1].split("--- SCRIPT END ---", 1)[0]
    lines = script.splitlines()
    scenes: list[dict] = []
    current: dict | None = None
    blocks: list[dict] = []
    pending_label: str | None = None
    pending_kind = "action"
    pending_start: float | None = None
    pending_end: float | None = None
    pending_text: list[str] = []
    parse_warnings: list[str] = []

    def flush() -> None:
        nonlocal pending_label, pending_text, pending_start, pending_end
        if pending_label is None or pending_start is None or pending_end is None:
            return
        speaker, emotion, raw = _speaker(pending_label)
        body = re.sub(r"\s+", " ", " ".join(pending_text)).strip().strip('"“”')
        block = {
            "kind": pending_kind, "speaker": speaker, "raw_label": pending_label,
            "emotion": emotion, "start": pending_start, "end": pending_end, "text": body,
        }
        blocks.append(block)
        if current is not None:
            current["blocks"].append(block)
        pending_label, pending_text = None, []
        pending_start = pending_end = None

    for line in lines:
        if _SCENE.match(line):
            flush()
            current = {"heading": "", "start": 0.0, "end": 0.0, "blocks": []}
            scenes.append(current)
            continue
        if current is None:
            continue
        if match := re.match(r"\s*Scene heading\s*:\s*(.*)", line, re.I):
            current["heading"] = match.group(1).replace(chr(0x2013), "-").replace(chr(0x2014), "-").strip()
            continue
        if match := _SCENE_START.match(line):
            try:
                current["start"] = parse_time(match.group(1))
            except ValueError as exc:
                raise ValueError(f"Invalid scene start: {match.group(1)}") from exc
            continue
        if match := _SCENE_END.match(line):
            try:
                current["end"] = parse_time(match.group(1))
            except ValueError as exc:
                raise ValueError(f"Invalid scene end: {match.group(1)}") from exc
            continue
        if header_match := _HEADER.match(line):
            if pending_start is not None:
                flush()
            elif pending_label is not None:
                pending_label, pending_text = None, []
            if pending_label is None:
                pending_label = header_match.group(1)
                pending_kind = _kind(pending_label)
                pending_text = [header_match.group(2)] if header_match.group(2) else []
            else:
                pending_text.append(line)
            continue
        if time_match := _TIMES.search(line):
            if pending_label is None:
                label_match = _HEADER.search(line)
                pending_label = label_match.group(1) if label_match else "ACTION"
                pending_kind = _kind(pending_label)
            elif pending_start is not None:
                flush()
            try:
                pending_start, pending_end = parse_time(time_match.group(1)), parse_time(time_match.group(2))
            except ValueError as exc:
                parse_warnings.append(f"Skipped block with invalid timestamp: {exc}")
                pending_label, pending_text = None, []
                pending_start = pending_end = None
            continue
        if pending_label is None:
            continue
        pending_text.append(line)
    flush()
    if not scenes:
        raise ValueError("No scenes found")
    blocks.sort(key=lambda block: (block["start"], block["end"]))
    duration = max([scene["end"] for scene in scenes] + [block["end"] for block in blocks] + [0.0])
    return {
        "number": number,
        "logline": logline_match.group(1).strip() if logline_match else "",
        "continuity_notes": re.sub(r"\s+", " ", notes_match.group(1)).strip() if notes_match else "",
        "duration": duration,
        "scenes": scenes,
        "blocks": blocks,
        "beats": build_beats(blocks),
        "parse_warnings": parse_warnings,
        "source": path.name,
    }


def build_beats(blocks: list[dict]) -> list[dict]:
    beats: list[dict] = []
    for category in ("dialogue", "action"):
        related = [block for block in blocks
                   if ("dialogue" if block["kind"] == "dialogue" else "action") == category]
        for block in related:
            if beats and beats[-1]["kind"] == category and block["start"] <= beats[-1]["end"]:
                beat = beats[-1]
                beat["end"] = max(beat["end"], block["end"])
                beat["blocks"].append(block)
            else:
                beats.append({"kind": category, "start": block["start"], "end": block["end"], "blocks": [block]})
    return sorted(beats, key=lambda beat: (beat["start"], beat["end"]))
