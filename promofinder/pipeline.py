from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Callable

from .bible import build_bible
from .campaign import build_campaign
from .candidates import generate_candidates
from .config import enabled_provider, load_config, model_name
from .export import write_exports
from .features import _rules, extract_features
from .judge import judge_episode
from .judge_cold import judge_top_promos
from .llm import BudgetExceeded, LLMClient
from .nudge import suggest_nudge
from .parse import parse_episode
from .preflight import preflight
from .rank import rank_promos
from .schemas import GlobalOrder
from .stitch import validate_stitched
from .validate import normalize_quote, quote_verified, validate_promo


def run_pipeline(folder: str | Path, output: str | Path | None = None,
                 heuristics_only: bool = False, resume: bool = False,
                 client: LLMClient | None = None, progress=None,
                 config_overrides: dict[str, str] | None = None,
                 session_calls: Callable[[], int] | None = None,
                 record_session_call: Callable[[], None] | None = None) -> dict:
    started = time.monotonic()
    config = load_config()
    if config_overrides:
        config.update(config_overrides)
    output = Path(output or config["OUTPUT_DIR"])
    config["OUTPUT_DIR"] = str(output)
    output.mkdir(parents=True, exist_ok=True)
    check = preflight(folder)
    episodes = {episode["number"]: episode for episode in check["files_parsed"]}
    if not episodes:
        raise ValueError(f"No valid episodes found in {folder}.")
    provider = "mock" if heuristics_only else enabled_provider(config)
    selected_model = "heuristics-only" if provider == "mock" else model_name(config, provider)
    llm = client or (LLMClient(config, session_calls=session_calls,
                               record_session_call=record_session_call) if provider != "mock" else None)
    stats_client = llm
    if llm and hasattr(llm, "protected_shingles"):
        for episode in episodes.values():
            source = Path(folder) / episode["source"]
            if source.is_file():
                llm.protect_text(source.read_text(encoding="utf-8", errors="replace"))
    bible = build_bible(list(episodes.values()), llm if llm and provider != "mock" else None)
    if bible.get("request_error"):
        stage_failures = [f'Bible request failed: {bible["request_error"]}']
        llm = None
    else:
        stage_failures = []
    first_mentions = {}
    for episode in episodes.values():
        searchable = " ".join(block["text"] + " " + (block["speaker"] or "") for block in episode["blocks"]).lower()
        for canonical, aliases in bible.get("characters", {}).items():
            for alias in [canonical, *aliases]:
                if alias.lower() in searchable:
                    first_mentions[alias.lower()] = min(first_mentions.get(alias.lower(), episode["number"]),
                                                        episode["number"])
    all_candidates, pruned, rejected = [], 0, []
    weights = _rules()["weights"]
    tokens_per_episode = {}
    for index, episode in enumerate(episodes.values(), 1):
        before = dict(stats_client.stats) if stats_client else {}
        candidates = generate_candidates(episode)
        for candidate in candidates:
            candidate["features"] = extract_features(candidate, episode, bible=bible,
                                                      first_mentions=first_mentions)
        candidates.sort(key=lambda item: (
            item["features"]["hook"] * weights["hook"] +
            item["features"]["cliffhanger"] * weights["cliffhanger"] +
            item["features"]["standalone"] * weights["standalone"]), reverse=True)
        pruned += max(0, len(candidates) - 6)
        short_list = candidates[:6]
        judged = []
        if llm and short_list:
            try:
                judged = judge_episode(episode, short_list, bible, llm)
            except BudgetExceeded as exc:
                stage_failures.append(f'Episode {episode["number"]}: {exc}')
                llm = None
            except Exception as exc:
                stage_failures.append(f'Episode {episode["number"]}: {type(exc).__name__}: {exc}')
                llm = None
        by_id = {item["id"]: item for item in judged}
        selected = judged if judged else short_list
        for candidate in selected:
            item = {**candidate}
            item["features"] = candidate["features"]
            item["segments"] = candidate["segments"]
            judgment = by_id.get(candidate["id"])
            if judgment:
                for field in ("hook_score", "cliffhanger_score", "standalone_score", "hook_line",
                              "cliffhanger_line", "why", "weakness", "hook_type", "quote_verified"):
                    item[field] = judgment[field]
            else:
                item["hook_score"] = item["features"]["hook"]
                item["cliffhanger_score"] = item["features"]["cliffhanger"]
                item["standalone_score"] = item["features"]["standalone"]
                item["hook_line"] = " ".join(item["features"]["hook_line"].split()[:8])
                item["cliffhanger_line"] = " ".join(item["features"]["cliffhanger_line"].split()[:8])
                item["hook_type"] = item["features"]["hook_type"]
                item["cold_clarity"] = None
                item["cold_viewer"] = "not run"
                item["quote_verified"] = True
            item["duration"] = sum(seg["end"] - seg["start"] for seg in item["segments"])
            all_candidates.append(item)
        if progress:
            progress(index, len(episodes), episode["number"])
        if stats_client:
            tokens_per_episode[str(episode["number"])] = {
                "input": stats_client.stats["input_tokens"] - before["input_tokens"],
                "output": stats_client.stats["output_tokens"] - before["output_tokens"],
                "calls": stats_client.stats["calls"] - before["calls"]}
    promos = rank_promos(all_candidates, int(config["MAX_PER_EPISODE"]))
    stitched = []
    if llm and promos:
        compact = [{"id": item["id"], "episode": item["segments"][0]["episode"],
                    "start": item["segments"][0]["start"], "end": item["segments"][0]["end"],
                    "hook": item.get("hook_line", "")[:120], "cliffhanger": item.get("cliffhanger_line", "")[:120],
                    "score": item["score"]} for item in promos[:40]]
        try:
            global_result = llm.complete_json(
                "Order these candidate promos for a new viewer. Return promo_id and one short reason for each "
                "ordered item. Propose at most 8 experimental stitched promos, each with ordered segments "
                "(episode, start, end), hook_line, cliffhanger_line, hook_type, and why. Use only supplied times "
                "and exact short quotes. Reasons must paraphrase and must not quote the screenplay. "
                "JSON shape: {\"order\":[{\"promo_id\":\"id\",\"reason\":\"text\"}],"
                "\"stitched\":[{\"segments\":[{\"episode\":1,\"start\":0,\"end\":25}],"
                "\"hook_line\":\"short quote\",\"cliffhanger_line\":\"short quote\","
                "\"hook_type\":\"mystery\",\"why\":\"text\"}]}. Candidates: " + json.dumps(compact),
                GlobalOrder, system="Use only supplied evidence. Do not use em dash or en dash.")
            positions = {item.promo_id: index for index, item in enumerate(global_result.order)}
            for item in promos:
                item["global_rank"] = positions.get(item["id"], 10_000)
            for proposal_model in global_result.stitched[:8]:
                proposal = proposal_model.model_dump()
                try:
                    segments = [{"episode": int(part["episode"]), "start": float(part["start"]),
                                 "end": float(part["end"])} for part in proposal["segments"]]
                    promo = {"id": "stitch-" + str(len(stitched) + 1), "segments": segments,
                             "hook_line": " ".join(str(proposal["hook_line"]).split()[:8]),
                             "cliffhanger_line": " ".join(str(proposal["cliffhanger_line"]).split()[:8]),
                             "hook_type": str(proposal["hook_type"]),
                             "why": ("This stitched proposal needs an editor review."
                                     if llm._contains_input_shingle(str(proposal["why"]))
                                     else str(proposal["why"])),
                             "experimental": True, "features": {"standalone": 6, "spoiler_risk": 1,
                             "context_debt": 0, "resolved_soon_after": False},
                             "duration": sum(part["end"] - part["start"] for part in segments)}
                    errors = validate_stitched(promo, episodes)
                    for part in segments:
                        episode = episodes.get(part["episode"])
                        if episode is None:
                            errors.append("episode not found")
                            continue
                        starts = {beat["start"] for beat in episode["beats"]}
                        ends = {beat["end"] for beat in episode["beats"]}
                        if part["start"] not in starts or part["end"] not in ends:
                            errors.append("segment is not snapped to beat edges")
                    if not quote_verified(promo["hook_line"], episodes.get(segments[0]["episode"], {})) or \
                            not quote_verified(promo["cliffhanger_line"], episodes.get(segments[-1]["episode"], {})):
                        errors.append("stitched quote is not verified")
                    first_ep = episodes.get(segments[0]["episode"], {})
                    last_ep = episodes.get(segments[-1]["episode"], {})
                    hook_key = normalize_quote(promo["hook_line"])
                    cliff_key = normalize_quote(promo["cliffhanger_line"])
                    if not any(hook_key and hook_key in normalize_quote(block["text"])
                               and segments[0]["start"] <= block["start"] <= segments[0]["start"] + 3
                               for block in first_ep.get("blocks", [])):
                        errors.append("stitched hook is not inside the opening three seconds")
                    if not any(cliff_key and cliff_key in normalize_quote(block["text"])
                               and segments[-1]["end"] - 4 <= block["end"] <= segments[-1]["end"]
                               for block in last_ep.get("blocks", [])):
                        errors.append("stitched cliffhanger is not inside the final four seconds")
                    opening_speakers = {block["speaker"] for block in first_ep.get("blocks", [])
                                        if segments[0]["start"] <= block["start"] <= segments[0]["end"]
                                        and block["speaker"]}
                    if len(opening_speakers) < 2:
                        errors.append("first segment does not establish context")
                    if errors:
                        rejected.append({"promo_id": promo["id"],
                                         "episodes": [part["episode"] for part in segments],
                                         "reasons": errors})
                    else:
                        for field, score in (("hook_score", 6), ("cliffhanger_score", 6),
                                             ("standalone_score", 6)):
                            promo[field] = score
                        stitched.append(promo)
                except (KeyError, TypeError, ValueError) as exc:
                    proposal_segments = proposal.get("segments")
                    rejected.append({"promo_id": f"stitch-{len(stitched) + 1}",
                                     "episodes": [part.get("episode") for part in proposal_segments
                                                  if isinstance(part, dict)]
                                     if isinstance(proposal_segments, list) else [],
                                     "reasons": [f"invalid model proposal: {type(exc).__name__}"]})
        except BudgetExceeded as exc:
            stage_failures.append(f"Global rank: {exc}")
            llm = None
        except Exception as exc:
            stage_failures.append(f"Global rank: {type(exc).__name__}: {exc}")
            llm = None
    promos.extend(stitched)
    accepted = []
    for promo in promos:
        if promo.get("experimental"):
            errors = validate_stitched(promo, episodes)
            if not errors:
                accepted.append(promo)
            else:
                rejected.append({"promo_id": promo["id"],
                                 "episodes": [part["episode"] for part in promo["segments"]],
                                 "reasons": errors})
        else:
            errors = validate_promo(promo, episodes)
            segment = promo["segments"][0]
            starts = {beat["start"] for beat in episodes[segment["episode"]]["beats"]}
            ends = {beat["end"] for beat in episodes[segment["episode"]]["beats"]}
            if not errors and segment["start"] in starts and segment["end"] in ends:
                accepted.append(promo)
            else:
                rejected.append({"promo_id": promo["id"],
                                 "episodes": [segment["episode"]],
                                 "reasons": errors or ["boundaries are not snapped to beats"]})
    non_overlapping = []
    for promo in sorted(accepted, key=lambda item: (item.get("score", 0), item["id"]), reverse=True):
        conflict = False
        for earlier in non_overlapping:
            for segment in promo["segments"]:
                for other in earlier["segments"]:
                    if segment["episode"] != other["episode"]:
                        continue
                    shared = max(0, min(segment["end"], other["end"]) - max(segment["start"], other["start"]))
                    shorter = min(segment["end"] - segment["start"], other["end"] - other["start"])
                    if shorter > 0 and shared / shorter > .30:
                        conflict = True
                        break
                if conflict:
                    break
            if conflict:
                break
        if conflict:
            rejected.append({"promo_id": promo["id"],
                             "episodes": [segment["episode"] for segment in promo["segments"]],
                             "reasons": ["overlaps another promo by more than 30 percent"]})
        else:
            non_overlapping.append(promo)
    accepted = non_overlapping
    promos = accepted[:int(config["TOP_N"])]
    if llm and promos:
        while True:
            pending = [promo for promo in promos[:15]
                       if not isinstance(promo.get("cold_viewer"), dict)]
            if not pending:
                break
            try:
                judge_top_promos(pending, episodes, llm, limit=len(pending))
            except BudgetExceeded as exc:
                stage_failures.append(str(exc))
                llm = None
                break
            except Exception as exc:
                stage_failures.append(f'Cold viewer {pending[0]["id"]}: {type(exc).__name__}: {exc}')
                llm = None
                break
            promos = rank_promos(promos, int(config["MAX_PER_EPISODE"]))
    for promo in promos:
        if not isinstance(promo.get("cold_viewer"), dict):
            promo["cold_viewer"] = "not run"
            promo["cold_clarity"] = None
    promos = rank_promos(promos, int(config["MAX_PER_EPISODE"]))
    for promo in promos[:20]:
        promo["nudge"] = suggest_nudge(promo, episodes)
    changed_nudges = [promo["nudge"]["score_delta"] for promo in promos[:20]
                      if promo.get("nudge", {}).get("changed")]
    campaign = build_campaign(promos, output)
    run_id = str(uuid.uuid4())
    report = {"run_id": run_id, "model": selected_model, "provider": provider,
              "episodes_parsed": len(episodes), "files_failed": json.dumps(check["files_failed"]),
              "preflight_health": check["health_score"], "candidates_generated": len(all_candidates),
              "candidates_pruned": pruned, "promos_ranked": len(promos),
              "promos_rejected": len(rejected), "failed_stages": json.dumps(stage_failures),
              "tokens_input": stats_client.stats["input_tokens"] if stats_client else 0,
              "tokens_output": stats_client.stats["output_tokens"] if stats_client else 0,
              "llm_calls": stats_client.stats["calls"] if stats_client else 0,
              "cache_hits": stats_client.stats["cache_hits"] if stats_client else 0,
              "retries": stats_client.stats["retries"] if stats_client else 0,
              "estimated_cost": stats_client.stats["estimated_cost"] if stats_client else 0,
              "unsafe_responses_omitted_from_raw": (
                  stats_client.stats["unsafe_responses_omitted_from_raw"] if stats_client else 0),
              "models_used": json.dumps(stats_client.stats["models_used"] if stats_client else []),
              "fallback_events": json.dumps(stats_client.stats["fallback_events"] if stats_client else []),
              "api_key_fallback_events": json.dumps(
                  stats_client.stats["api_key_fallback_events"] if stats_client else []),
              "quota_events": json.dumps(stats_client.stats["quota_events"] if stats_client else []),
              "rate_headers": json.dumps(stats_client.stats["rate_headers"] if stats_client else []),
              "rate_limit_events": json.dumps(stats_client.stats["rate_limit_events"] if stats_client else []),
              "tokens_per_episode": json.dumps(tokens_per_episode),
              "nudge_changed": len(changed_nudges),
              "nudge_average_delta": round(sum(changed_nudges) / len(changed_nudges), 3) if changed_nudges else 0,
              "runtime_seconds": round(time.monotonic() - started, 2),
              "heuristics_only": provider == "mock" or not bool(llm), "resume": resume}
    smoke_limits = output / "smoke_rate_limits.json"
    if not smoke_limits.exists():
        smoke_limits = Path("outputs/smoke_rate_limits.json")
    if smoke_limits.is_file():
        report["observed_model_rate_limits"] = json.dumps(
            json.loads(smoke_limits.read_text(encoding="utf-8")))
    previous_live_path = Path("outputs/first_live_run_metrics.json")
    if previous_live_path.is_file():
        previous_live = json.loads(previous_live_path.read_text(encoding="utf-8"))
        report["initial_live_run_id"] = previous_live.get("run_id", "")
        report["initial_live_tokens_input"] = int(previous_live.get("tokens_input", 0))
        report["initial_live_tokens_output"] = int(previous_live.get("tokens_output", 0))
        report["initial_live_calls"] = int(previous_live.get("llm_calls", 0))
        report["initial_live_runtime_seconds"] = float(previous_live.get("runtime_seconds", 0))
        report["initial_live_estimated_cost"] = float(previous_live.get("estimated_cost", 0))
        previous_failures = previous_live.get("failed_stages", [])
        if isinstance(previous_failures, str):
            try:
                previous_failures = json.loads(previous_failures)
            except json.JSONDecodeError:
                previous_failures = [previous_failures]
        report["initial_live_failed_stages"] = json.dumps(previous_failures)
        report["measured_total_tokens"] = (
            report["tokens_input"] + report["tokens_output"] +
            report["initial_live_tokens_input"] + report["initial_live_tokens_output"])
    preflight_export = {key: value for key, value in check.items() if key != "files_parsed"}
    for key in ("bad_blocks", "beyond_scene", "malformed_blocks"):
        for item in preflight_export.get(key, []):
            block = item.get("block") if isinstance(item, dict) else None
            if isinstance(block, dict):
                block.pop("text", None)
    (output / "preflight.json").write_text(json.dumps(preflight_export, indent=2), encoding="utf-8")
    (output / "run_meta.json").write_text(json.dumps({"run_id": run_id, "model": selected_model,
                                                      "provider": provider, "promos": [p["id"] for p in promos]},
                                                     indent=2), encoding="utf-8")
    if provider != "mock" and not stage_failures:
        models_dir = output / "model_runs"
        models_dir.mkdir(exist_ok=True)
        (models_dir / f"{run_id}.json").write_text(json.dumps({
            "run_id": run_id, "provider": provider, "model": selected_model,
            "ids": [promo["id"] for promo in promos], "complete": True}, indent=2), encoding="utf-8")
    write_exports(output, promos, rejected, report, campaign)
    return {"run_id": run_id, "promos": promos, "rejected": rejected, "report": report,
            "preflight": check, "episodes": episodes}
