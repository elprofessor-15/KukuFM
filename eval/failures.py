import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promofinder.parse import parse_episode
from promofinder.validate import normalize_quote


def main():
    promos = json.loads(Path("outputs/promos.json").read_text(encoding="utf-8"))
    episodes = {episode["number"]: episode for path in Path("data").glob("*.txt")
                if (episode := parse_episode(path))}
    flagged = []
    for promo in promos:
        segment = promo["segments"][0]
        episode = episodes.get(segment["episode"], {})
        hook = normalize_quote(str(promo.get("hook_line") or ""))
        opening = [block for block in episode.get("blocks", [])
                   if segment["start"] <= block["start"] <= segment["start"] + 3]
        camera_only = bool(hook) and any(block["kind"] == "camera"
                                         and hook in normalize_quote(block["text"]) for block in opening) \
            and not any(block["kind"] != "camera"
                        and hook in normalize_quote(block["text"]) for block in opening)
        cold = promo.get("cold_viewer")
        cold_confused = cold == "not run" or (isinstance(cold, dict)
                                               and (not cold.get("conflict") or cold.get("confusing")))
        if (promo["features"]["standalone"] < 5 or promo["features"]["context_debt"] > 0
                or promo["features"]["resolved_soon_after"] or camera_only
                or cold_confused or len(promo["segments"]) > 1):
            flagged.append(promo)
    lines = ["# Candidates for human quality review", ""]
    for promo in flagged:
        lines.append(f'- {promo["id"]}: episode {promo["segments"][0]["episode"]}, '
                     f'{promo.get("hook_line", "")} / {promo.get("cliffhanger_line", "")}')
    Path("eval/failure_candidates.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Flagged {len(flagged)} promos.")


if __name__ == "__main__":
    main()
