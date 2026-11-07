import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promofinder.candidates import generate_candidates
from promofinder.llm import LLMError, _parse_json
from promofinder.parse import parse_episode
from promofinder.timeutil import parse_time
from promofinder.stitch import validate_stitched
from promofinder.validate import quote_verified, validate_promo


def main():
    promos = json.loads(Path("outputs/promos.json").read_text(encoding="utf-8"))
    episodes = {episode["number"]: episode for path in Path("data").glob("*.txt")
                if (episode := parse_episode(path))}
    valid = sum(not (validate_stitched(promo, episodes) if promo.get("experimental")
                     else validate_promo(promo, episodes)) for promo in promos)
    verified = [bool(promo.get("hook_line")) and bool(promo.get("cliffhanger_line"))
                and quote_verified(promo.get("hook_line", ""),
                                   episodes[promo["segments"][0]["episode"]])
                and quote_verified(promo.get("cliffhanger_line", ""),
                                   episodes[promo["segments"][-1]["episode"]]) for promo in promos]
    duration_ok = sum(20 <= promo["duration"] <= 60 for promo in promos)
    snap_checks = []
    for promo in promos:
        for segment in promo["segments"]:
            episode = episodes[segment["episode"]]
            starts = {beat["start"] for beat in episode["beats"]}
            ends = {beat["end"] for beat in episode["beats"]}
            snap_checks.append(segment["start"] in starts and segment["end"] in ends)
    rejected = json.loads(Path("outputs/rejected.json").read_text(encoding="utf-8"))
    cold = [promo for promo in promos if isinstance(promo.get("cold_viewer"), dict)]
    unclear = sum(not bool(promo["cold_viewer"].get("conflict")) for promo in cold)
    def metric(count, total):
        return {"count": count, "total": total, "rate": count / total if total else None}

    metrics = {
        "validity": metric(valid, len(promos)),
        "quote_verification": metric(sum(verified), len(verified)),
        "duration_compliance": metric(duration_ok, len(promos)),
        "snap_rate": metric(sum(snap_checks), len(snap_checks)),
        "rejected_share": metric(len(rejected), len(promos) + len(rejected)),
        "cold_viewer_conflict_missing": metric(unclear, len(cold)),
    }
    candidates = {}
    for episode in episodes.values():
        candidates.update({item["id"]: (item, episode) for item in generate_candidates(episode)})
    proposals = []
    for path in Path("outputs/raw_llm").glob("*.json"):
        response = json.loads(path.read_text(encoding="utf-8")).get("response", {})
        if isinstance(response, str):
            try:
                raw = _parse_json(response)
            except LLMError:
                continue
        else:
            raw = response
        for item in raw.get("judgments", []):
            candidate_pair = candidates.get(item.get("candidate_id"))
            if candidate_pair:
                candidate, episode = candidate_pair
                segment = candidate["segments"][0]
                try:
                    hook_time = parse_time(item["hook_time"])
                except (KeyError, ValueError):
                    hook_time = -1
                valid_proposal = (20 <= candidate["duration"] <= 60
                                  and bool(item.get("hook_line"))
                                  and bool(item.get("cliffhanger_line"))
                                  and quote_verified(item["hook_line"], episode)
                                  and quote_verified(item["cliffhanger_line"], episode)
                                  and segment["start"] <= hook_time <= segment["start"] + 3)
                proposals.append(valid_proposal)
    metrics["raw_proposal_validity"] = metric(sum(proposals), len(proposals))
    for label, item in metrics.items():
        rate = f'{item["rate"]:.3f}' if item["rate"] is not None else "not available"
        print(f'{label}: {item["count"]}/{item["total"]} ({rate})')
    Path("eval/auto_checks.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
