import subprocess
from pathlib import Path


def test_tracked_text_has_no_long_dash_characters():
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=False)
    paths = {Path(name) for name in result.stdout.splitlines()}
    paths.update(path for path in Path(".").rglob("*") if path.is_file()
                 and not {".git", ".venv", ".cache", "data", "__pycache__"}.intersection(path.parts))
    bad = []
    for path in sorted(paths):
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "\u2014" in text or "\u2013" in text:
                bad.append(str(path))
    assert not bad, f"Long dash found in: {bad}"
