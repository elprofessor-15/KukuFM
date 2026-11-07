from pathlib import Path

import pytest

from promofinder.parse import parse_episode
from promofinder.preflight import preflight
from promofinder.timeutil import format_time, parse_time


def test_real_episodes_parse_in_order():
    files = sorted(Path("data").glob("episode-*.txt"))
    assert len(files) == 50
    parsed = [parse_episode(path) for path in (files[0], files[-1])]
    for episode in parsed:
        assert episode["blocks"]
        assert episode["blocks"][0]["start"] <= episode["blocks"][-1]["start"]
        assert episode["duration"] >= episode["blocks"][-1]["end"]
        assert episode["scenes"]
        assert episode["beats"]
    assert any(block["speaker"] for episode in parsed for block in episode["blocks"])
    assert any(block["emotion"] for episode in parsed for block in episode["blocks"])


def test_junk_files_are_skipped(tmp_path):
    (tmp_path / "._junk.txt").write_text("not an episode")
    (tmp_path / "__MACOSX").mkdir()
    (tmp_path / "__MACOSX" / "episode-002.txt").write_text("not an episode")
    report = preflight(tmp_path)
    assert not report["files_parsed"]
    assert not report["files_failed"]


def test_bad_files_are_reported_without_stopping(tmp_path):
    (tmp_path / "episode-001-bad.txt").write_text("not a screenplay")
    report = preflight(tmp_path)
    assert not report["files_parsed"]
    assert report["files_failed"][0]["reason"] == "No scenes found"


@pytest.mark.parametrize(("value", "expected"), [("00:05.50", 5.5), ("1:02:03", 3723)])
def test_time_formats(value, expected):
    assert parse_time(value) == expected


def test_time_format_round_trip():
    assert format_time(65.25) == "01:05.25"
