from __future__ import annotations

import re
from collections import defaultdict
import sys

from .schemas import Bible


def build_bible(episodes: list[dict], client=None) -> dict:
    if client:
        notes = [f'E{item["number"]}: {item["logline"]} {item["continuity_notes"]}' for item in episodes]
        try:
            intro = ("Make a compact series bible from episode notes. Include a two-line premise, characters as "
                     "canonical name to alias list, relationships, and major reveals with episode. "
                     "Do not invent details. Paraphrase notes, do not quote them.\n")
            token_limit = max(500, int(client.config["TOKENS_PER_MINUTE"]) - 2000)
            groups, current = [], []
            size = len(intro) // 4
            for note in notes:
                if current and size + len(note) // 4 > token_limit:
                    groups.append(current)
                    current, size = [], len(intro) // 4
                current.append(note)
                size += len(note) // 4
            if current:
                groups.append(current)
            summaries = [client.complete_json(intro + "\n".join(group), Bible,
                                              system="Return only source-grounded JSON. Do not use em dash or en dash.")
                         for group in groups]
            if len(summaries) > 1:
                merged = client.complete_json(intro + "\n".join(
                    item.model_dump_json() for item in summaries), Bible,
                    system="Merge the supplied partial bibles. Keep only facts supported by them. "
                    "Do not use em dash or en dash.")
                result = merged
            else:
                result = summaries[0]
            return {**result.model_dump(), "degraded": False}
        except Exception as exc:
            print(f"Bible request failed, using degraded regex bible ({type(exc).__name__}).",
                  file=sys.stderr)
            error = type(exc).__name__
        else:
            error = None
    else:
        error = None
    names: dict[str, set[str]] = defaultdict(set)
    for episode in episodes:
        for line in (episode["logline"], episode["continuity_notes"]):
            for name in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b", line):
                names[name.upper()].add(name)
    return {"premise": "Degraded fallback, no premise summary was generated.",
            "characters": {key: sorted(value) for key, value in names.items()},
            "relationships": [], "reveals": [], "degraded": True, "request_error": error}
