from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"\b[\w']+\b", re.UNICODE)


def words(text: str) -> list[str]:
    return [word.lower() for word in TOKEN.findall(text)]


def shingles(text: str) -> set[tuple[str, ...]]:
    tokens = words(text)
    return {tuple(tokens[index:index + 10]) for index in range(max(0, len(tokens) - 9))}


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.splitlines()


def collect_quotes(value: object, allowed: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"hook_line", "cliffhanger_line"} and isinstance(child, str) \
                    and len(words(child)) <= 25:
                allowed.add(child)
            else:
                collect_quotes(child, allowed)
    elif isinstance(value, list):
        for child in value:
            collect_quotes(child, allowed)


def raw_response_quotes(value: object, allowed: set[str],
                        promo_quotes: dict[str, tuple[str, str]]) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("response"), str):
        return True
    response = re.sub(r"<think>.*?</think>", "", value["response"], flags=re.I | re.S).strip()
    if "\u2014" in response or "\u2013" in response:
        return False
    start = response.find("{")
    if start < 0:
        return False
    try:
        parsed, _ = json.JSONDecoder().raw_decode(response[start:])
    except json.JSONDecodeError:
        return False
    for judgment in _judgments(parsed):
        evidence = promo_quotes.get(str(judgment.get("candidate_id", "")))
        if not evidence:
            continue
        for field, promo_quote in zip(("hook_line", "cliffhanger_line"), evidence):
            quote = judgment.get(field)
            if not isinstance(quote, str) or not quote or len(words(quote)) > 25:
                continue
            quote_words, evidence_words = words(quote), words(promo_quote)
            if evidence_words and quote_words[:len(evidence_words)] == evidence_words:
                allowed.add(quote)
    return all(not isinstance(quote, str) or len(words(quote)) <= 25
               for quote in _quote_fields(parsed))


def _quote_fields(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"hook_line", "cliffhanger_line"}:
                yield child
            else:
                yield from _quote_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from _quote_fields(child)


def _judgments(value: object):
    if isinstance(value, dict):
        if isinstance(value.get("candidate_id"), str):
            yield value
        else:
            for child in value.values():
                yield from _judgments(child)
    elif isinstance(value, list):
        for child in value:
            yield from _judgments(child)


def main() -> int:
    data = ROOT / "data"
    if not data.exists():
        print("Leak check: data directory is missing.")
        return 2
    corpus = set()
    for path in data.rglob("*"):
        if path.is_file():
            corpus.update(shingles(path.read_text(encoding="utf-8", errors="replace")))
    bad_paths = [name for name in tracked_files() if name == "data" or name.startswith("data/")]
    history = subprocess.run(["git", "log", "--all", "--name-only", "--pretty=format:"],
                             cwd=ROOT, capture_output=True, text=True, check=False)
    bad_paths.extend(name for name in history.stdout.splitlines() if name == "data" or name.startswith("data/"))
    allowed = set()
    promo_quotes = {}
    output = ROOT / "outputs"
    promos_file = output / "promos.json"
    if promos_file.exists():
        try:
            promos = json.loads(promos_file.read_text(encoding="utf-8"))
            collect_quotes(promos, allowed)
            promo_quotes = {
                str(promo.get("id")): (str(promo.get("hook_line", "")),
                                       str(promo.get("cliffhanger_line", "")))
                for promo in promos if promo.get("id")
            }
        except (json.JSONDecodeError, OSError):
            print("Leak check: promos.json could not be read.")
            return 2
    raw_dir = output / "raw_llm"
    invalid_raw = []
    if raw_dir.exists():
        for path in raw_dir.glob("*.json"):
            try:
                if not raw_response_quotes(json.loads(path.read_text(encoding="utf-8")),
                                           allowed, promo_quotes):
                    invalid_raw.append(path.name)
            except (json.JSONDecodeError, OSError):
                print(f"Leak check: unreadable raw response file: {path.name}")
                return 2
    candidates = []
    for name in tracked_files():
        path = ROOT / name
        if path.is_file():
            candidates.append((name, path.read_text(encoding="utf-8", errors="replace")))
    if output.exists():
        candidates.extend((str(path.relative_to(ROOT)), path.read_text(encoding="utf-8", errors="replace"))
                          for path in output.rglob("*") if path.is_file())
    commits = subprocess.run(["git", "rev-list", "--branches", "--remotes"], cwd=ROOT,
                             capture_output=True, text=True, check=False).stdout.splitlines()
    historical_files = set()
    for commit in commits:
        names = subprocess.run(["git", "ls-tree", "-r", "--name-only", commit],
                               cwd=ROOT, capture_output=True, text=True, check=False).stdout.splitlines()
        historical_files.update(name for name in names if name == "data" or name.startswith("data/"))
        for name in names:
            if name == "data" or name.startswith("data/"):
                continue
            historical = subprocess.run(["git", "show", f"{commit}:{name}"], cwd=ROOT,
                                        capture_output=True, text=True, check=False)
            if historical.returncode == 0:
                candidates.append((f"git history:{commit[:8]}:{name}", historical.stdout))
    hits = []
    for name, text in candidates:
        if name.startswith("outputs/") or name.startswith("git history:") and ":outputs/" in name:
            for quote in allowed:
                if quote:
                    text = text.replace(quote, " ")
        if shingles(text) & corpus:
            hits.append(name)
    bad_paths.extend(historical_files)
    if bad_paths or hits or invalid_raw:
        print(f"Leak check failed: {len(set(bad_paths))} data paths in history, "
              f"{len(hits)} matching files, {len(invalid_raw)} invalid raw responses.")
        for name in sorted(set(hits + bad_paths + [f"outputs/raw_llm/{item}" for item in invalid_raw]))[:20]:
            print(f"Possible confidential match: {name}")
        return 1
    print("Leak check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
