import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promofinder.candidates import generate_candidates
from promofinder.config import load_config
from promofinder.features import extract_features
from promofinder.judge import judge_episode
from promofinder.llm import LLMClient
from promofinder.parse import parse_episode
from promofinder.preflight import preflight


def main():
    config = load_config()
    episodes = preflight(config["DATA_DIR"])["files_parsed"][:5]
    client = LLMClient(config)
    for episode in episodes:
        path = Path(config["DATA_DIR"]) / episode["source"]
        client.protect_text(path.read_text(encoding="utf-8", errors="replace"))
    scores = {"heuristics": [], "llm": [], "hybrid": []}
    for episode in episodes:
        windows = generate_candidates(episode)
        for item in windows:
            item["features"] = extract_features(item, episode)
        judged = judge_episode(episode, windows[:6], {"premise": ""}, client)
        scores["heuristics"].append(max((x["features"]["hook"] + x["features"]["cliffhanger"]) / 2
                                       for x in windows))
        scores["llm"].append(max((x["hook_score"] + x["cliffhanger_score"]) / 2 for x in judged) if judged else 0)
        scores["hybrid"].append(max(((x["hook_score"] + x["cliffhanger_score"] +
                                      x["features"]["standalone"]) / 3 for x in judged), default=0))
    result = {key: round(sum(values) / len(values), 2) if values else 0 for key, values in scores.items()}
    result["episodes"] = len(episodes)
    result["llm_windows_per_episode"] = 6
    result["method"] = "Heuristics score every generated window. LLM and hybrid scores use the first six generated windows without heuristic ranking."
    print(json.dumps(result, indent=2))
    Path("eval/ablation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
