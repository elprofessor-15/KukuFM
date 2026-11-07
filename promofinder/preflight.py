from pathlib import Path

from .parse import parse_episode


def preflight(folder: str | Path) -> dict:
    root = Path(folder)
    parsed, failed = [], []
    if not root.is_dir():
        return {"files_parsed": [], "files_failed": [{"file": str(root), "reason": "Folder does not exist"}],
                "missing_episodes": [], "bad_blocks": [], "malformed_blocks": [],
                "beyond_scene": [], "health_score": 0}
    for path in sorted(root.rglob("*.txt")):
        if "__MACOSX" in path.parts or path.name.startswith("._"):
            continue
        try:
            parsed.append(parse_episode(path))
        except Exception as exc:
            failed.append({"file": path.name, "reason": str(exc)})
    numbers = {episode["number"] for episode in parsed}
    missing = list(range(min(numbers), max(numbers) + 1)) if numbers else []
    missing = [number for number in missing if number not in numbers]
    bad_blocks, malformed_blocks, beyond_scene = [], [], []
    for episode in parsed:
        malformed_blocks.extend({"episode": episode["number"], "warning": warning}
                                for warning in episode.get("parse_warnings", []))
        for block in episode["blocks"]:
            if block["end"] < block["start"]:
                bad_blocks.append({"episode": episode["number"], "block": block})
            scenes = [s for s in episode["scenes"] if s["start"] <= block["start"] <= s["end"]]
            if scenes and block["end"] > max(s["end"] for s in scenes):
                beyond_scene.append({"episode": episode["number"], "block": block})
    total = len(parsed) + len(failed) + len(missing) + len(bad_blocks) + len(malformed_blocks) + len(beyond_scene)
    deductions = len(failed) + len(missing) + len(bad_blocks) + len(malformed_blocks) + len(beyond_scene)
    health = round(100 * (1 - deductions / max(1, total)))
    return {"files_parsed": parsed, "files_failed": failed, "missing_episodes": missing,
            "bad_blocks": bad_blocks, "malformed_blocks": malformed_blocks,
            "beyond_scene": beyond_scene, "health_score": health}
