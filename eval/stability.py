import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promofinder.candidates import generate_candidates
from promofinder.config import load_config
from promofinder.features import extract_features
from promofinder.judge import judge_episode
from promofinder.llm import LLMClient
from promofinder.preflight import preflight


def main():
    config = load_config()
    episodes = preflight(config["DATA_DIR"])["files_parsed"][:5]
    first, second, repeat = [], [], []
    primary_scores, second_scores, repeat_scores = {}, {}, {}
    with tempfile.TemporaryDirectory(prefix="promofinder-stability-") as temporary_dir:
        temporary_output = Path(temporary_dir) / "outputs"
        temporary_output.mkdir()
        client = LLMClient(config | {"OUTPUT_DIR": str(temporary_output)})
        repeat_client = LLMClient(config | {"CACHE_DIR": str(Path(temporary_dir) / "cache"),
                                            "OUTPUT_DIR": str(temporary_output)})
        for episode in episodes:
            path = Path(config["DATA_DIR"]) / episode["source"]
            protected_text = path.read_text(encoding="utf-8", errors="replace")
            client.protect_text(protected_text)
            repeat_client.protect_text(protected_text)
        for episode in episodes:
            candidates = generate_candidates(episode)
            for candidate in candidates:
                candidate["features"] = extract_features(candidate, episode)
            candidates.sort(key=lambda item: (
                item["features"]["hook"] * .28 + item["features"]["cliffhanger"] * .27 +
                item["features"]["standalone"] * .25), reverse=True)
            top = candidates[:2]
            for candidate in top:
                primary = judge_episode(episode, [candidate], {"premise": ""}, client,
                                       model=config["MODEL_NAME"])
                alternate = judge_episode(episode, [candidate], {"premise": ""}, client,
                                          model=config["SECOND_MODEL_NAME"])
                again = judge_episode(episode, [candidate], {"premise": ""}, repeat_client,
                                      model=config["MODEL_NAME"])
                first.extend(item["candidate_id"] for item in primary)
                second.extend(item["candidate_id"] for item in alternate)
                repeat.extend(item["candidate_id"] for item in again)
                primary_scores.update({item["candidate_id"]: _score(item) for item in primary})
                second_scores.update({item["candidate_id"]: _score(item) for item in alternate})
                repeat_scores.update({item["candidate_id"]: _score(item) for item in again})
    def top_ten(items):
        return [item["candidate_id"] for item in sorted(
            items, key=lambda row: _score(row), reverse=True)[:10]]

    def overlap(left, right):
        return len(set(left) & set(right)) / 10

    primary_top = top_ten([{"candidate_id": item, "score": primary_scores.get(item, 0)} for item in first])
    second_top = top_ten([{"candidate_id": item, "score": second_scores.get(item, 0)} for item in second])
    repeat_top = top_ten([{"candidate_id": item, "score": repeat_scores.get(item, 0)} for item in repeat])
    common = set(primary_scores) & set(repeat_scores)
    score_deltas = [abs(primary_scores[item] - repeat_scores[item]) for item in common]
    result = {"primary_vs_second_model_top10_overlap": overlap(primary_top, second_top),
              "same_model_repeat_top10_overlap": overlap(primary_top, repeat_top),
              "same_model_score_variance": (
                  round(sum((delta / 2) ** 2 for delta in score_deltas) / len(score_deltas), 4)
                  if score_deltas else None),
              "same_model_mean_absolute_score_delta": (
                  round(sum(score_deltas) / len(score_deltas), 3) if score_deltas else None),
              "episodes": len(episodes), "primary_model": config["MODEL_NAME"],
              "second_model": config["SECOND_MODEL_NAME"],
              "candidates_per_episode": 2,
              "candidates_per_request": 1,
              "note": "Single-candidate requests keep the second-model response within its observed output-token limit.",
              "same_model_repeat_cache_hits": repeat_client.stats["cache_hits"],
              "same_model_live_repeat_calls": repeat_client.stats["calls"]}
    print(json.dumps(result, indent=2))
    Path("eval/stability.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    runs_dir = Path(config["OUTPUT_DIR"]) / "model_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for path in runs_dir.glob("stability-*.json"):
        path.unlink()
    for model, ids in ((config["MODEL_NAME"], primary_top),
                       (config["SECOND_MODEL_NAME"], second_top)):
        role = "primary" if model == config["MODEL_NAME"] else "second"
        run_id = f"stability-{role}"
        (runs_dir / f"{run_id}.json").write_text(json.dumps({
            "run_id": run_id, "provider": config["MODEL_PROVIDER"], "model": model,
            "ids": ids, "sampled_episodes": len(episodes), "complete": True}, indent=2), encoding="utf-8")


def _score(item):
    if "hook_score" not in item:
        return item.get("score", 0)
    return (item["hook_score"] + item["cliffhanger_score"] + item["standalone_score"]) / 3


if __name__ == "__main__":
    main()
