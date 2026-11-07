import re


_TIME = re.compile(r"(?<!\d)(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?(?!\d)")


def parse_time(value: str) -> float:
    match = _TIME.search(value.strip())
    if not match:
        raise ValueError(f"Invalid timestamp: {value!r}")
    hours, minutes, seconds, fraction = match.groups()
    centiseconds = int((fraction or "0").ljust(2, "0")[:2])
    total = int(seconds) + int(minutes) * 60 + (int(hours or 0) * 3600)
    if int(seconds) >= 60 or int(minutes) >= 60 and hours is not None:
        raise ValueError(f"Out-of-range timestamp: {value!r}")
    return total + centiseconds / 100


def format_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    minutes, remainder = divmod(centiseconds, 6000)
    whole, fraction = divmod(remainder, 100)
    return f"{minutes:02d}:{whole:02d}.{fraction:02d}"
