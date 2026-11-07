from __future__ import annotations

import csv
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from promofinder.config import load_config
from promofinder.parse import parse_episode
from promofinder.pipeline import run_pipeline
from promofinder.preflight import preflight
from promofinder.stitch import validate_stitched
from promofinder.upload import extract_episode_zip
from promofinder.validate import normalize_quote, quote_in_interval, validate_promo


failures = 0


def check(label, action):
    global failures
    try:
        detail = action()
        print(f"PASS: {label}" + (f": {detail}" if detail else ""))
    except Exception as exc:
        failures += 1
        print(f"FAIL: {label}: {type(exc).__name__}: {exc}")


def command(args, timeout=600):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-3000:])
    return result.stdout.strip()


def verify_tests():
    output = command([sys.executable, "-m", "pytest", "-q"])
    print(output)


def verify_full_run(heuristics_only, output_dir, include_result=False):
    config = load_config()
    result = run_pipeline(config["DATA_DIR"], output_dir, heuristics_only=heuristics_only)
    if result["report"]["episodes_parsed"] != 50:
        raise AssertionError(f'Expected 50 episodes, parsed {result["report"]["episodes_parsed"]}')
    failures = result["report"].get("failed_stages", [])
    failures = json.loads(failures) if isinstance(failures, str) else failures
    broken = [item for item in failures if "UnboundLocalError" in item or "NameError" in item]
    if broken:
        raise AssertionError(f"Pipeline hit a programming error: {broken}")
    if include_result:
        return result
    return f'{result["report"]["episodes_parsed"]} episodes parsed, {len(result["promos"])} promos'


def renamed_show_test(parent):
    source = preflight("data")["files_parsed"][:5]
    target = Path(parent) / "alternate_show"
    target.mkdir()
    replacements = {}
    generic_speaker_terms = {"GUARD"}
    for episode in source:
        for block in episode["blocks"]:
            speaker = block.get("speaker")
            if speaker:
                for name in sorted(speaker.split(), key=len, reverse=True):
                    if (len(name) > 3 and name not in {"FORMER", "YOUNG", "LADY"}
                            and name.upper() not in generic_speaker_terms):
                        replacements.setdefault(name, f"Person{len(replacements) + 1}")
    for index, episode in enumerate(source, 101):
        original = Path("data") / episode["source"]
        text = original.read_text(encoding="utf-8")
        for name, replacement in replacements.items():
            text = re.sub(r"\b" + re.escape(name) + r"\b", replacement, text, flags=re.I)
        text = re.sub(r"(?im)^EPISODE NUMBER\s*:\s*.*$", f"EPISODE NUMBER: Episode {index}", text, count=1)
        script_start = text.find("--- SCRIPT START ---")
        script_end = text.find("--- SCRIPT END ---", script_start)
        prefix, body, suffix = text[:script_start], text[script_start:script_end], text[script_end:]
        scenes = list(re.finditer(r"(?m)^\s*SCENE\s+\d+\s*$", body))
        if len(scenes) > 2:
            body = body[:scenes[2].start()]
        text = prefix + body + suffix
        (target / f"chapter-{index}.txt").write_text(text, encoding="utf-8")
    output_dir = Path(parent) / "alternate_output"
    result = run_pipeline(target, output_dir, heuristics_only=True)
    if result["report"]["episodes_parsed"] != 5:
        raise AssertionError("Renamed sample was not parsed as five episodes.")
    source_files = list(ROOT.glob("*.py")) + list((ROOT / "promofinder").glob("*.py")) + \
        list((ROOT / "scripts").glob("*.py")) + list((ROOT / "eval").glob("*.py"))
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
    for name in replacements:
        if re.search(r"\b" + re.escape(name) + r"\b", source_text, flags=re.I):
            raise AssertionError("A source module includes an input-specific speaker name.")
    return "5 renamed and trimmed episodes parsed"


def verify_app_and_zip(parent):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    if app.exception:
        raise AssertionError("; ".join(error.message for error in app.exception))
    if len(app.tabs) != 8:
        raise AssertionError(f"Expected eight tabs, got {len(app.tabs)}")
    archive_path = Path(parent) / "episodes.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in sorted(Path("data").glob("episode-*.txt"))[:3]:
            archive.write(path, path.name)
    upload_dir = extract_episode_zip(archive_path.read_bytes())
    try:
        result = preflight(upload_dir)
        if len(result["files_parsed"]) != 3:
            raise AssertionError("ZIP upload did not parse three episodes.")
        outcome = run_pipeline(upload_dir, Path(parent) / "zip_output", heuristics_only=True)
        if outcome["report"]["episodes_parsed"] != 3:
            raise AssertionError("ZIP analysis did not complete.")
    finally:
        shutil.rmtree(upload_dir)
    return "8 tabs loaded; 3-episode ZIP processed"


def verify_headless_server():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
         "--server.port", str(port)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Streamlit exited with code {process.returncode}.")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        return "headless health endpoint returned 200"
            except Exception:
                time.sleep(.5)
        raise RuntimeError("Streamlit health endpoint did not become ready.")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def verify_promos():
    root = Path("outputs")
    promos = json.loads((root / "promos.json").read_text(encoding="utf-8"))
    episodes = {episode["number"]: episode for episode in preflight("data")["files_parsed"]}
    errors, segments = [], []
    for promo in promos:
        if promo.get("experimental"):
            errors.extend(validate_stitched(promo, episodes))
            for segment in promo["segments"]:
                episode = episodes[segment["episode"]]
                if segment["start"] not in {beat["start"] for beat in episode["beats"]}:
                    errors.append("stitched start is not a beat edge")
                if segment["end"] not in {beat["end"] for beat in episode["beats"]}:
                    errors.append("stitched end is not a beat edge")
            first = promo["segments"][0]
            last = promo["segments"][-1]
            if not quote_in_interval(promo["hook_line"], episodes[first["episode"]],
                                     first["start"], first["start"] + 3):
                errors.append("stitched hook is not inside the opening")
            if not quote_in_interval(promo["cliffhanger_line"], episodes[last["episode"]],
                                     last["end"] - 4, last["end"], use_block_end=True):
                errors.append("stitched cliffhanger is not inside the ending")
        else:
            errors.extend(validate_promo(promo, episodes))
            segment = promo["segments"][0]
            episode = episodes[segment["episode"]]
            if segment["start"] not in {beat["start"] for beat in episode["beats"]}:
                errors.append("start is not a beat edge")
            if segment["end"] not in {beat["end"] for beat in episode["beats"]}:
                errors.append("end is not a beat edge")
        segments.extend(promo["segments"])
    if errors:
        raise AssertionError(f"Independent promo validation found {len(errors)} failures.")
    for index, segment in enumerate(segments):
        for other in segments[index + 1:]:
            if segment["episode"] != other["episode"]:
                continue
            shared = max(0, min(segment["end"], other["end"]) - max(segment["start"], other["start"]))
            shorter = min(segment["end"] - segment["start"], other["end"] - other["start"])
            if shorter and shared / shorter > .30:
                raise AssertionError("Two promos overlap by more than 30 percent.")
    return f"{len(promos)} promos independently valid"


def verify_export_files():
    root = Path("outputs")
    required = ["promos.json", "promos.csv", "promos.md", "cut_sheet.csv", "campaign_plan.md",
                "campaign_plan.csv", "rejected.json", "run_report.md", "preflight.json", "run_meta.json",
                "smoke_results.json", "smoke_rate_limits.json", "first_live_run_metrics.json"]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise AssertionError(f"Missing exports: {missing}")
    promos = json.loads((root / "promos.json").read_text(encoding="utf-8"))
    with (root / "cut_sheet.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = sum(len(promo["segments"]) for promo in promos)
    if len(rows) != expected:
        raise AssertionError(f"Cut sheet has {len(rows)} rows, expected {expected}.")
    expected_headers = {
        "promos.csv": {"rank", "id", "score", "episode", "in", "out", "hook_type"},
        "cut_sheet.csv": {"promo_id", "rank", "episode", "in", "out", "segment_order", "duration"},
        "campaign_plan.csv": {"day", "promo_id", "episode", "hook_type", "reason"}}
    for name, columns in expected_headers.items():
        with (root / name).open(encoding="utf-8", newline="") as stream:
            headers = set(next(csv.reader(stream)))
        if not columns.issubset(headers):
            raise AssertionError(f"{name} is missing columns.")
    if len(list((root / "raw_llm").glob("*.json"))) == 0:
        raise AssertionError("Raw LLM response files are missing.")
    if len(list(root.glob("*.edl.json"))) != len(promos):
        raise AssertionError("EDL JSON files do not match the promo count.")
    for promo in promos:
        for segment in promo["segments"]:
            if not re.fullmatch(r"\d{2,}:\d{2}\.\d{2}", segment["in"]):
                raise AssertionError("Promo JSON has an invalid in timestamp.")
            if not re.fullmatch(r"\d{2,}:\d{2}\.\d{2}", segment["out"]):
                raise AssertionError("Promo JSON has an invalid out timestamp.")
    return f"{len(promos)} promos, {len(rows)} cut rows, expected columns and raw exports"


def verify_pdf(parent):
    target = Path(parent) / "solution_doc_draft.pdf"
    output = command([sys.executable, "-m", "docs.build_pdf", "--draft", "--output", str(target)])
    from pypdf import PdfReader
    pages = len(PdfReader(str(target)).pages)
    if pages > 2:
        raise AssertionError(f"Draft PDF has {pages} pages.")
    return output


def verify_stability_report():
    path = Path("eval/stability.json")
    if not path.is_file():
        raise AssertionError("The live stability evaluation is missing.")
    result = json.loads(path.read_text(encoding="utf-8"))
    required = {"primary_vs_second_model_top10_overlap", "same_model_repeat_top10_overlap",
                "same_model_score_variance", "same_model_mean_absolute_score_delta",
                "episodes", "primary_model", "second_model", "same_model_live_repeat_calls"}
    if not required.issubset(result) or result["episodes"] != 5:
        raise AssertionError("The stability report is incomplete.")
    if result["same_model_live_repeat_calls"] < 1:
        raise AssertionError("The stability rerun did not make a live same-model request.")
    return f'5 episodes, top-10 overlap {result["primary_vs_second_model_top10_overlap"]}'


def verify_git():
    status = command(["git", "status", "--porcelain"])
    if status:
        raise AssertionError("Worktree is not clean.")
    remote = command(["git", "remote", "get-url", "origin"])
    local = command(["git", "rev-parse", "HEAD"])
    refs = command(["git", "ls-remote", "origin", "refs/heads/main"])
    if not refs or refs.split()[0] != local:
        raise AssertionError("Remote main does not match local HEAD.")
    private = command(["gh", "repo", "view", "elprofessor-15/pocketFM_MVP",
                       "--json", "isPrivate", "-q", ".isPrivate"])
    if private.lower() != "true":
        raise AssertionError("GitHub repository is not private.")
    return f"private repo, matching HEAD at {local[:12]}, {remote}"


def main():
    config = load_config()
    key_names = (("GROQ_API_KEY", "GROQ_API_KEY2") if config["MODEL_PROVIDER"] == "groq"
                 else ("OPENAI_COMPAT_API_KEY",))
    if config["USE_LLM"].lower() == "true" and not any(config.get(name) for name in key_names):
        print(f"BLOCKED: {' or '.join(key_names)} are empty. Add a key to .env before live verification.")
        return 2
    check("1. pytest suite", verify_tests)
    check("2. injected provider and validation failures",
          lambda: command([sys.executable, "-m", "pytest", "-q", "tests/test_failures.py"]))
    with tempfile.TemporaryDirectory(prefix="promofinder-verify-") as temp:
        check("3. full heuristics run on the 50-episode pack",
              lambda: verify_full_run(True, Path(temp) / "heuristics"))
        live_output = Path(temp) / "live"
        live_result = {}

        def verify_live():
            first = verify_full_run(False, live_output, include_result=True)
            if first["report"]["provider"] != config["MODEL_PROVIDER"]:
                raise AssertionError("Live run used an unexpected provider.")
            if not first["report"]["llm_calls"] and not first["report"]["cache_hits"]:
                raise AssertionError("Full live run had neither API calls nor cache hits.")
            if any(not isinstance(promo.get("cold_viewer"), dict)
                   for promo in first["promos"][:15]):
                raise AssertionError("A final top-15 promo has no cold-viewer result.")
            live_result["first"] = first
            return (f'input tokens {first["report"]["tokens_input"]}, output tokens '
                    f'{first["report"]["tokens_output"]}, cost {first["report"]["estimated_cost"]}')

        check("4. full Groq live run", verify_live)

        def verify_cache():
            saved = (live_output / "promos.json").read_bytes()
            second = run_pipeline(config["DATA_DIR"], live_output, resume=True)
            if (live_output / "promos.json").read_bytes() != saved:
                raise AssertionError("Cached rerun changed the promo output.")
            if second["report"]["llm_calls"] != 0:
                raise AssertionError("Cached rerun made live model calls.")
            return f'zero live calls, {second["report"]["cache_hits"]} cache hits, identical promo JSON'

        check("5. cached rerun and determinism", verify_cache)
        check("6. renamed and trimmed second-show test", lambda: renamed_show_test(temp))
        check("7. Streamlit AppTest and ZIP upload", lambda: verify_app_and_zip(temp))
        check("7. headless Streamlit server", verify_headless_server)
        check("8. independent promo validation", verify_promos)
        check("10. export files and columns", verify_export_files)
        check("13. automated quality checks",
              lambda: command([sys.executable, "-m", "eval.auto_checks"]))
        check("13. blind-label scoring",
              lambda: command([sys.executable, "-m", "eval.score"]))
        check("13. five-episode ablation",
              lambda: command([sys.executable, "-m", "eval.ablation"]))
        check("13. five-episode model stability",
              lambda: command([sys.executable, "-m", "eval.stability"], timeout=1800))
        check("13. live model stability results", verify_stability_report)
        check("13. human failure candidates",
              lambda: command([sys.executable, "-m", "eval.failures"]))
        check("13. evaluation report",
              lambda: command([sys.executable, "-m", "eval.build_report"]))
        check("9. confidential data leak guard",
              lambda: command([sys.executable, "scripts/leak_check.py"]))
        check("11. draft PDF page count", lambda: verify_pdf(temp))
    check("12. clean worktree, private GitHub repo, and remote HEAD", verify_git)
    print(f"Verification result: {'PASS' if failures == 0 else 'FAIL'}, {failures} failed check(s).")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
