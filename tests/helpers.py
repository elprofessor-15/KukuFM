from pathlib import Path

from promofinder.parse import parse_episode


def sample_episode(tmp_path: Path, number: int = 1) -> dict:
    source = (
        f"EPISODE NUMBER: Episode {number}\n"
        "EPISODE LOGLINE: A family fights over a hidden deed.\n"
        "CONTINUITY NOTES: One person knows the secret.\n"
        "--- SCRIPT START ---\n"
        "SCENE 01\n"
        "Scene heading: INT. ROOM - DAY\n"
        "Scene start: 00:00.00\n"
        "Scene end: 01:00.00\n"
        "Actions and dialogue:\n"
        "**PERSON ONE (Angry):**\n"
        "Start: (00:00.00) | End: (00:02.00)\n"
        '"You betrayed me!"\n'
        "**ACTION:**\n"
        "Start: (00:03.00) | End: (00:05.00)\n"
        "A locked door slams shut.\n"
        "**PERSON TWO (Worried):**\n"
        "Start: (00:10.00) | End: (00:12.00)\n"
        '"The secret is the deed."\n'
        "**PERSON ONE:**\n"
        "Start: (00:20.00) | End: (00:22.00)\n"
        '"Who opened the door?"\n'
        "**SOUND FX:**\n"
        "Start: (00:46.00) | End: (00:48.00)\n"
        "A dark sting follows.\n"
        "**PERSON TWO:**\n"
        "Start: (00:55.00) | End: (01:00.00)\n"
        '"We will meet again!"\n'
        "--- SCRIPT END ---\n"
    )
    path = tmp_path / f"episode-{number:03d}-sample.txt"
    path.write_text(source, encoding="utf-8")
    return parse_episode(path)
