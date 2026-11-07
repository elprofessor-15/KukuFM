from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path
import shutil


def extract_episode_zip(data: bytes) -> Path:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            relative = Path(entry.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("The ZIP contains a path outside the upload folder.")
            if entry.file_size > 20_000_000:
                raise ValueError("A ZIP entry exceeds the 20 MB file limit.")
        target_dir = Path(tempfile.mkdtemp(prefix="promofinder-upload-")).resolve()
        try:
            archive.extractall(target_dir)
        except (OSError, zipfile.BadZipFile):
            shutil.rmtree(target_dir)
            raise
    return target_dir
