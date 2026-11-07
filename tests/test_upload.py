import io
import shutil
import zipfile
from pathlib import Path

import pytest

from promofinder.preflight import preflight
from promofinder.upload import extract_episode_zip
from tests.helpers import sample_episode


def test_episode_zip_upload_path(tmp_path):
    episode = sample_episode(tmp_path)
    path = tmp_path / episode["source"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(path.name, path.read_bytes())
    directory = extract_episode_zip(buffer.getvalue())
    try:
        result = preflight(directory)
        assert len(result["files_parsed"]) == 1
        assert not result["files_failed"]
    finally:
        shutil.rmtree(directory)


def test_zip_path_traversal_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../outside.txt", "not a screenplay")
    with pytest.raises(ValueError, match="outside"):
        extract_episode_zip(buffer.getvalue())
