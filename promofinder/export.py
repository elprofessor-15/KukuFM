from __future__ import annotations

import csv
import copy
import json
from pathlib import Path

from .timeutil import format_time


def write_exports(output: str | Path, promos: list[dict], rejected: list[dict],
                  report: dict, campaign: list[dict]) -> None:
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    export_promos = copy.deepcopy(promos)
    for promo in export_promos:
        for segment in promo["segments"]:
            segment["in"] = format_time(segment["start"])
            segment["out"] = format_time(segment["end"])
    (root / "promos.json").write_text(json.dumps(export_promos, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "rejected.json").write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["rank", "id", "score", "episode", "in", "out", "duration", "hook_type",
              "hook_line", "cliffhanger_line", "rank_reason", "experimental"]
    with (root / "promos.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for promo in promos:
            segment = promo["segments"][0]
            writer.writerow({"rank": promo.get("rank"), "id": promo["id"], "score": promo["score"],
                             "episode": segment["episode"], "in": format_time(segment["start"]),
                             "out": format_time(segment["end"]), "duration": round(promo["duration"], 2),
                             "hook_type": promo.get("hook_type", promo["features"]["hook_type"]),
                             "hook_line": promo.get("hook_line", promo["features"]["hook_line"]),
                             "cliffhanger_line": promo.get("cliffhanger_line", promo["features"]["cliffhanger_line"]),
                             "rank_reason": promo["rank_reason"], "experimental": promo.get("experimental", False)})
    cut_fields = ["promo_id", "rank", "episode", "in", "out", "segment_order", "duration"]
    with (root / "cut_sheet.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=cut_fields)
        writer.writeheader()
        for promo in promos:
            for index, segment in enumerate(promo["segments"], 1):
                writer.writerow({"promo_id": promo["id"], "rank": promo.get("rank"),
                                 "episode": segment["episode"], "in": format_time(segment["start"]),
                                 "out": format_time(segment["end"]), "segment_order": index,
                                 "duration": round(segment["end"] - segment["start"], 2)})
    lines = ["# Ranked promos", ""]
    for promo in promos:
        segment_lines = [f'Segment {index}: episode {segment["episode"]}, '
                         f'{format_time(segment["start"])} to {format_time(segment["end"])}'
                         for index, segment in enumerate(promo["segments"], 1)]
        cold = promo.get("cold_viewer", "not run")
        if isinstance(cold, dict):
            cold_notes = (f'Conflict: {cold.get("conflict", "")}. '
                          f'Confusing: {", ".join(cold.get("confusing", [])) or "none reported"}. '
                          f'Keep watching: {cold.get("keep_watching", False)}. '
                          f'Expected next: {cold.get("expect_next", "")}')
        else:
            cold_notes = str(cold)
        lines += [f'## {promo["rank"]}. {promo["id"]}',
                  *segment_lines,
                  f'Score: {promo["score"]}.',
                  f'Hook: {promo.get("hook_line", promo["features"]["hook_line"])}',
                  f'Cliffhanger: {promo.get("cliffhanger_line", promo["features"]["cliffhanger_line"])}',
                  f'Why: {promo.get("why", promo["features"]["why"])}',
                  f'Cold viewer: {cold_notes}',
                  f'Rank reason: {promo["rank_reason"]}', ""]
        (root / f'{promo["id"]}.edl.json').write_text(json.dumps({
            "id": promo["id"], "segments": [
                {"episode": seg["episode"], "in": format_time(seg["start"]), "out": format_time(seg["end"])}
                for seg in promo["segments"]]}, indent=2), encoding="utf-8")
    (root / "promos.md").write_text("\n".join(lines), encoding="utf-8")
    campaign_fields = ["day", "promo_id", "episode", "hook_type", "reason"]
    with (root / "campaign_plan.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=campaign_fields)
        writer.writeheader()
        writer.writerows(campaign)
    (root / "campaign_plan.md").write_text(
        "# Posting plan\n\n" + "\n".join(
            f'Day {slot["day"]}: {slot["promo_id"]}, episode {slot["episode"]}. {slot["reason"]}'
            for slot in campaign), encoding="utf-8")
    (root / "run_report.md").write_text(
        "# Run report\n\n" + "\n".join(f"- {key}: {value}" for key, value in report.items()),
        encoding="utf-8")
