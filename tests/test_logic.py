from promofinder.candidates import generate_candidates
from promofinder.features import extract_features
from promofinder.judge import judge_episode
from promofinder.nudge import suggest_nudge
from promofinder.pipeline import judge_top_promos as pipeline_cold_judge
from promofinder.rank import rank_promos
from promofinder.schemas import ColdViewer, EpisodeJudgment, EpisodeJudgments
from promofinder.timeutil import format_time
from promofinder.validate import (normalize_quote, overlap_iou, quote_in_interval, quote_verified,
                                  validate_promo)
from tests.helpers import sample_episode


def test_candidates_are_valid_and_snap_to_beats(tmp_path):
    episode = sample_episode(tmp_path)
    candidates = generate_candidates(episode)
    assert candidates
    edges_start = {beat["start"] for beat in episode["beats"]}
    edges_end = {beat["end"] for beat in episode["beats"]}
    for item in candidates:
        segment = item["segments"][0]
        assert segment["start"] in edges_start
        assert segment["end"] in edges_end
        assert 20 <= item["duration"] <= 60


def test_quotes_and_validation_use_episode_text(tmp_path):
    episode = sample_episode(tmp_path)
    block = next(block for block in episode["blocks"] if block["text"])
    assert quote_verified(block["text"], episode)
    assert normalize_quote("Exact,   text!") == normalize_quote("Exact text")
    promo = {"segments": [{"episode": episode["number"], "start": -1, "end": 70}],
             "duration": 71, "hook_line": "", "cliffhanger_line": ""}
    assert validate_promo(promo, {episode["number"]: episode})
    assert overlap_iou((0, 10), (5, 15)) == .3333333333333333


def test_reactive_opening_without_setup_loses_hook_points():
    episode = {"number": 1, "logline": "A family uncovers a secret.",
               "blocks": [{"kind": "dialogue", "start": 0.0, "end": 1.0,
                           "speaker": "PERSON", "emotion": None, "text": "What did you do?"}]}
    candidate = {"segments": [{"episode": 1, "start": 0.0, "end": 25.0}], "duration": 25.0}
    features = extract_features(candidate, episode)
    assert features["reactive_opening"]
    assert features["hook"] == 2.5


def test_ranking_caps_episode_count(tmp_path):
    episode = sample_episode(tmp_path)
    candidate = generate_candidates(episode)[0]
    feature = extract_features(candidate, episode)
    promos = [{"id": str(index), "segments": candidate["segments"], "duration": candidate["duration"],
               "features": feature.copy()} for index in range(4)]
    assert len(rank_promos(promos, max_per_episode=2)) == 2


def test_nudge_uses_half_second_targets_and_valid_beat_edges(tmp_path):
    episode = sample_episode(tmp_path)
    candidate = generate_candidates(episode)[0]
    promo = {**candidate, "features": extract_features(candidate, episode)}
    suggestion = suggest_nudge(promo, {episode["number"]: episode})
    if suggestion["changed"]:
        edges_start = {beat["start"] for beat in episode["beats"]}
        edges_end = {beat["end"] for beat in episode["beats"]}
        start = suggestion["suggested"]["start"]
        end = suggestion["suggested"]["end"]
        assert start in edges_start
        assert end in edges_end
        assert abs((start - candidate["segments"][0]["start"]) * 2
                   - round((start - candidate["segments"][0]["start"]) * 2)) < 1e-8
        assert abs((end - candidate["segments"][0]["end"]) * 2
                   - round((end - candidate["segments"][0]["end"]) * 2)) < 1e-8


def test_bad_model_quotes_are_dropped_and_replaced_with_verified_evidence(tmp_path):
    episode = sample_episode(tmp_path)
    candidate = next(item for item in generate_candidates(episode)
                     if (features := extract_features(item, episode))["hook_line"]
                     and features["cliffhanger_line"])
    candidate["features"] = features
    segment = candidate["segments"][0]

    class Client:
        def complete_json(self, *args, **kwargs):
            return EpisodeJudgments(judgments=[EpisodeJudgment(
                candidate_id=candidate["id"], hook_score=8, cliffhanger_score=8,
                standalone_score=7, hook_line="fabricated hook", hook_time=format_time(segment["start"]),
                cliffhanger_line="fabricated cliffhanger", hook_type="mystery", why="Test.",
                weakness="Test.")])

    result = judge_episode(episode, [candidate], {"premise": ""}, Client())[0]
    assert not result["quote_verified"]
    assert result["weakness"] == "unverified quote"
    assert quote_in_interval(result["hook_line"], episode, segment["start"], segment["start"] + 3)
    assert quote_in_interval(result["cliffhanger_line"], episode, segment["end"] - 4, segment["end"],
                             use_block_end=True)


def test_pipeline_cold_judge_sets_clarity_and_confusion(tmp_path):
    episode = sample_episode(tmp_path)
    promo = {"id": "sample", "segments": [{"episode": 1, "start": 0.0, "end": 60.0}],
             "standalone_score": 7}

    class Client:
        def complete_json(self, *args, **kwargs):
            return ColdViewer(people=["Person one"], conflict="A hidden deed", confusing=[],
                              keep_watching=True, expect_next="A confrontation")

    result = pipeline_cold_judge([promo], {1: episode}, Client())
    assert result[0]["cold_viewer"]["conflict"] == "A hidden deed"
    assert result[0]["cold_clarity"] == 8
    assert result[0]["cold_clarity_score"] == 8
