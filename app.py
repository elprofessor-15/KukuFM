from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path

import streamlit as st

from promofinder import __version__
from promofinder.config import load_config, model_name
from promofinder.campaign import build_campaign
from promofinder.estimate import estimate_run
from promofinder.export import write_exports
from promofinder.features import extract_features
from promofinder.parse import parse_episode
from promofinder.pipeline import run_pipeline
from promofinder.preflight import preflight
from promofinder.rank import rank_promos, rerank_feedback
from promofinder.stitch import validate_stitched
from promofinder.timeutil import format_time
from promofinder.upload import extract_episode_zip
from promofinder.validate import quote_in_interval, quote_verified, validate_promo


st.set_page_config(page_title="KukuFM PromoFinder", page_icon=None, layout="wide")
try:
    secrets = dict(st.secrets)
except FileNotFoundError:
    secrets = {}
config = load_config(secrets)

if config.get("APP_PASSWORD"):
    password = st.text_input("App password", type="password")
    if password != config["APP_PASSWORD"]:
        st.info("Enter the app password to continue.")
        st.stop()

st.title("KukuFM PromoFinder")
st.caption("Find, rank, and review short promo windows in screenplay files.")
tabs = st.tabs(["Run", "Results", "Promo detail", "Campaign", "Coverage", "Label", "Compare models", "About"])

with tabs[0]:
    st.subheader("Run")
    uploaded = st.file_uploader("Upload episode ZIP", type=["zip"])
    folder = st.text_input("Or use an episode folder", value=config["DATA_DIR"])
    use_heuristics = st.toggle("Heuristics only", value=False)
    providers = ["groq", "openai_compatible", "anthropic"]
    selected_provider = config["MODEL_PROVIDER"] if config["MODEL_PROVIDER"] in providers else "groq"
    provider = st.selectbox("Model provider", providers, index=providers.index(selected_provider))
    model = st.text_input("Model", value=model_name(config, provider))
    key = st.text_input("Optional API key for this session", type="password")
    data_dir = folder
    if uploaded is not None:
        digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
        if st.session_state.get("upload_digest") != digest:
            try:
                st.session_state["upload_dir"] = str(extract_episode_zip(uploaded.getvalue()))
            except (ValueError, zipfile.BadZipFile) as exc:
                st.error(f"Could not read uploaded ZIP: {exc}")
                st.stop()
            st.session_state["upload_digest"] = digest
        data_dir = st.session_state["upload_dir"]
        st.session_state["active_data_dir"] = data_dir
    else:
        st.session_state["active_data_dir"] = data_dir
    pre = preflight(data_dir)
    st.write(f'Preflight: {len(pre["files_parsed"])} parsed, {len(pre["files_failed"])} failed, '
             f'{len(pre["missing_episodes"])} missing episode numbers, health {pre["health_score"]}/100.')
    estimate = estimate_run(pre["files_parsed"], requests_per_minute=int(config["REQUESTS_PER_MINUTE"]))
    st.caption(f'Estimate: {estimate["calls"]} calls, about {estimate["estimated_input_tokens"]} input tokens, '
               f'about {estimate["estimated_minutes"]} minutes at the configured request rate.')
    overrides = {"MODEL_PROVIDER": provider, "MODEL_NAME": model}
    provider_model_key = {"openai_compatible": "OPENAI_COMPAT_MODEL",
                          "anthropic": "ANTHROPIC_MODEL"}.get(provider)
    if provider_model_key:
        overrides[provider_model_key] = model
    if key:
        overrides[{"groq": "GROQ_API_KEY", "openai_compatible": "OPENAI_COMPAT_API_KEY",
                   "anthropic": "ANTHROPIC_API_KEY"}[provider]] = key
    if st.button("Run analysis"):
        try:
            bar = st.progress(0)
            status = st.empty()
            result = run_pipeline(data_dir, heuristics_only=use_heuristics,
                                  config_overrides=overrides,
                                  session_calls=lambda: st.session_state.get("hosted_llm_calls", 0),
                                  record_session_call=lambda: st.session_state.update(
                                      hosted_llm_calls=st.session_state.get("hosted_llm_calls", 0) + 1),
                                  progress=lambda current, total, episode:
                                  (bar.progress(current / total), status.write(f"Episode {episode}")))
            st.success(f'Run complete. {len(result["promos"])} promos passed validation.')
        except Exception as exc:
            st.error(f"Run stopped: {exc}")
    if st.button("Resume from cache"):
        try:
            result = run_pipeline(data_dir, resume=True, heuristics_only=use_heuristics,
                                  config_overrides=overrides,
                                  session_calls=lambda: st.session_state.get("hosted_llm_calls", 0),
                                  record_session_call=lambda: st.session_state.update(
                                      hosted_llm_calls=st.session_state.get("hosted_llm_calls", 0) + 1))
            st.success(f'Run completed with {len(result["promos"])} promos.')
        except Exception as exc:
            st.error(f"Resume stopped: {exc}")

with tabs[1]:
    st.subheader("Results")
    path = Path(config["OUTPUT_DIR"]) / "promos.json"
    if path.exists():
        promos = json.loads(path.read_text(encoding="utf-8"))
        if st.button("Re-rank using editor feedback"):
            promos = rerank_feedback(promos, Path(config["OUTPUT_DIR"]) / "feedback.jsonl")
            path.write_text(json.dumps(promos, indent=2), encoding="utf-8")
            st.success("Scores adjusted by up to one point for promos with the same hook type.")
        scores = [float(item["score"]) for item in promos]
        min_score, max_score = (min(scores), max(scores)) if scores else (0.0, 10.0)
        chosen = st.slider("Score range", min_score, max_score, (min_score, max_score))
        hook_types = sorted({item.get("hook_type", item["features"]["hook_type"]) for item in promos})
        selected_types = st.multiselect("Hook type", hook_types, default=hook_types)
        episodes = sorted({item["segments"][0]["episode"] for item in promos})
        selected_episodes = st.multiselect("Episode", episodes, default=episodes)
        selected_stitched = st.selectbox("Stitched", ["Any", "Yes", "No"])
        spoiler_limit = st.slider("Maximum spoiler risk", 0.0, 5.0, 5.0, .5)
        rows = [item for item in promos if chosen[0] <= item["score"] <= chosen[1]
                and item.get("hook_type", item["features"]["hook_type"]) in selected_types
                and item["segments"][0]["episode"] in selected_episodes
                and item["features"]["spoiler_risk"] <= spoiler_limit
                and (selected_stitched == "Any" or (len(item["segments"]) > 1) == (selected_stitched == "Yes"))]
        st.dataframe([{"rank": p["rank"], "episode": p["segments"][0]["episode"],
                       "score": p["score"], "hook_type": p.get("hook_type"),
                       "spoiler_risk": p["features"]["spoiler_risk"],
                       "validation": "valid", "stitched": len(p["segments"]) > 1} for p in rows],
                     width="stretch")
        st.download_button("Download promos JSON", json.dumps(promos, indent=2), "promos.json")
    else:
        st.info("Run the analysis to create results.")

with tabs[2]:
    st.subheader("Promo detail and feedback")
    path = Path(config["OUTPUT_DIR"]) / "promos.json"
    if path.exists():
        promos = json.loads(path.read_text(encoding="utf-8"))
        selected = st.selectbox("Promo", promos, format_func=lambda item: f'{item["rank"]}: {item["id"]}')
        st.write("Segments", selected["segments"])
        active_folder = st.session_state.get("active_data_dir", config["DATA_DIR"])
        episode = next((item for item in preflight(active_folder)["files_parsed"]
                        if item["number"] == selected["segments"][0]["episode"]), None)
        if episode:
            segment = selected["segments"][0]
            st.markdown("Script excerpt")
            for block in episode["blocks"]:
                if segment["start"] <= block["start"] <= segment["end"]:
                    label = f'{format_time(block["start"])} {block["speaker"] or block["kind"]}: {block["text"]}'
                    if any(quote and quote in block["text"] for quote in
                           (selected.get("hook_line"), selected.get("cliffhanger_line"))):
                        st.markdown(f"**{label}**")
                    else:
                        st.write(label)
        st.write("Hook", selected.get("hook_line", ""))
        st.write("Cliffhanger", selected.get("cliffhanger_line", ""))
        st.bar_chart(selected.get("score_breakdown", {}))
        st.write("Cold viewer", selected.get("cold_viewer", "not run"))
        st.write("Nudge suggestion", selected.get("nudge", "not available"))
        decision = st.radio("Decision", ["accept", "reject"], horizontal=True)
        segment = selected["segments"][0]
        edit_start = st.number_input("Start time in seconds", min_value=0.0, value=float(segment["start"]), step=.5)
        edit_end = st.number_input("End time in seconds", min_value=0.0, value=float(segment["end"]), step=.5)
        note = st.text_input("Editor note")
        nudge_accepted = st.checkbox("Accept the nudge", value=False)
        if st.button("Save feedback"):
            active_folder = st.session_state.get("active_data_dir", config["DATA_DIR"])
            pre = preflight(active_folder)
            episode = next((item for item in pre["files_parsed"] if item["number"] == segment["episode"]), None)
            starts = {beat["start"] for beat in episode["beats"]} if episode else set()
            ends = {beat["end"] for beat in episode["beats"]} if episode else set()
            suggestion = selected.get("nudge", {})
            if nudge_accepted and suggestion.get("changed"):
                edit_start = suggestion["suggested"]["start"]
                edit_end = suggestion["suggested"]["end"]
            if edit_start not in starts or edit_end not in ends or not 20 <= edit_end - edit_start <= 60:
                st.error("Edited boundaries must snap to beat edges and keep a 20 to 60 second duration.")
                st.stop()
            selected["segments"][0]["start"] = edit_start
            selected["segments"][0]["end"] = edit_end
            selected["segments"][0]["in"] = format_time(edit_start)
            selected["segments"][0]["out"] = format_time(edit_end)
            selected["duration"] = sum(item["end"] - item["start"] for item in selected["segments"])
            edited_candidate = {"segments": [selected["segments"][0]], "duration": edit_end - edit_start}
            fresh = extract_features(edited_candidate, episode)
            selected["hook_line"] = fresh["hook_line"]
            if len(selected["segments"]) == 1:
                selected["cliffhanger_line"] = fresh["cliffhanger_line"]
                selected["cliffhanger_score"] = fresh["cliffhanger"]
            selected["hook_score"] = fresh["hook"]
            selected["hook_type"] = fresh["hook_type"]
            selected["features"].update({field: fresh[field] for field in (
                "hook", "cliffhanger", "density", "speaker_count", "emotion_shifts",
                "central_conflict", "speakers", "character_pair", "hook_type")})
            selected["why"] = fresh["why"]
            selected["cold_viewer"] = "not run after boundary edit"
            selected["cold_clarity"] = None
            if len(selected["segments"]) == 1:
                errors = validate_promo(selected, {episode["number"]: episode})
            else:
                all_episodes = {item["number"]: item for item in pre["files_parsed"]}
                first, last = selected["segments"][0], selected["segments"][-1]
                errors = validate_stitched(selected, all_episodes)
                if not quote_verified(selected["hook_line"], episode) or not quote_in_interval(
                        selected["hook_line"], episode, first["start"], first["start"] + 3):
                    errors.append("edited hook evidence is not in the opening three seconds")
                last_episode = all_episodes[last["episode"]]
                if not quote_verified(selected["cliffhanger_line"], last_episode) or not quote_in_interval(
                        selected["cliffhanger_line"], last_episode, last["end"] - 4, last["end"],
                        use_block_end=True):
                    errors.append("cliffhanger evidence is not in the final four seconds")
            if errors:
                st.error("Edited promo failed validation: " + "; ".join(errors))
                st.stop()
            selected["quote_verified"] = True
            promos = rank_promos(promos, int(config["MAX_PER_EPISODE"]))
            output_dir = Path(config["OUTPUT_DIR"])
            rejected_path = output_dir / "rejected.json"
            rejected = json.loads(rejected_path.read_text(encoding="utf-8")) if rejected_path.exists() else []
            report_path = output_dir / "run_report.md"
            report = {}
            if report_path.exists():
                for line in report_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("- ") and ": " in line:
                        field, value = line[2:].split(": ", 1)
                        report[field] = value
            campaign = build_campaign(promos, output_dir)
            write_exports(output_dir, promos, rejected, report, campaign)
            target = Path(config["OUTPUT_DIR"]) / "feedback.jsonl"
            with target.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"promo_id": selected["id"], "decision": decision, "note": note,
                                         "hook_type": selected.get("hook_type"),
                                         "nudge_accepted": nudge_accepted}) + "\n")
            st.success("Feedback saved.")
    else:
        st.info("Run the analysis to see promo details.")

with tabs[3]:
    st.subheader("Campaign")
    plan = Path(config["OUTPUT_DIR"]) / "campaign_plan.csv"
    if plan.exists():
        st.dataframe(list(csv.DictReader(plan.open(encoding="utf-8"))), width="stretch")
        st.download_button("Download campaign CSV", plan.read_bytes(), "campaign_plan.csv")
    else:
        st.info("Campaign output is not available yet.")

with tabs[4]:
    st.subheader("Coverage")
    path = Path(config["OUTPUT_DIR"]) / "promos.json"
    if path.exists():
        promos = json.loads(path.read_text(encoding="utf-8"))
        active_folder = st.session_state.get("active_data_dir", config["DATA_DIR"])
        episode_numbers = [item["number"] for item in preflight(active_folder)["files_parsed"]]
        rejected_path = Path(config["OUTPUT_DIR"]) / "rejected.json"
        rejected = json.loads(rejected_path.read_text(encoding="utf-8")) if rejected_path.exists() else []
        counts = {}
        hooks = {}
        hook_by_episode = {}
        for promo in promos:
            episode = promo["segments"][0]["episode"]
            kind = promo.get("hook_type", promo["features"]["hook_type"])
            counts[episode] = counts.get(episode, 0) + 1
            hooks[kind] = hooks.get(kind, 0) + 1
            hook_by_episode[(episode, kind)] = hook_by_episode.get((episode, kind), 0) + 1
        st.write("Promos by episode")
        st.bar_chart(counts)
        st.write("Promos by hook type")
        st.bar_chart(hooks)
        coverage = []
        for episode in episode_numbers:
            if counts.get(episode):
                coverage.append({"episode": episode, "promos": counts[episode], "reason": ""})
                continue
            reasons = list(dict.fromkeys(
                reason for item in rejected if episode in item.get("episodes", [])
                for reason in item.get("reasons", [])))
            coverage.append({"episode": episode, "promos": 0,
                             "reason": "; ".join(reasons[:2]) if reasons
                             else "No valid window made the ranked list."})
        st.write("Episode and hook coverage")
        st.dataframe([{"episode": episode, "hook_type": kind, "promos": count}
                      for (episode, kind), count in sorted(hook_by_episode.items())], width="stretch")
        st.write("Episodes with no ranked promo and why")
        st.dataframe([row for row in coverage if row["promos"] == 0], width="stretch")
    else:
        st.info("Run the analysis to see coverage.")

with tabs[5]:
    st.subheader("Blind labels")
    folder = Path(st.session_state.get("active_data_dir", config["DATA_DIR"]))
    pre = preflight(folder)
    episodes = pre["files_parsed"]
    labeled_file = Path("eval/labels.csv")
    labeled = len(list(csv.DictReader(labeled_file.open(encoding="utf-8")))) if labeled_file.exists() else 0
    st.write(f"{labeled} labeled")
    if episodes:
        episode = st.selectbox("Episode", episodes, format_func=lambda item: str(item["number"]))
        beats = episode["beats"]
        if beats:
            labels = [f'{beat["start"]:.2f} to {beat["end"]:.2f}, {beat["kind"]}' for beat in beats]
            start_index = st.selectbox("Start beat", range(len(beats)), format_func=lambda i: labels[i])
            end_index = st.selectbox("End beat", range(len(beats)), format_func=lambda i: labels[i])
            note = st.text_input("Label note")
            if st.button("Save blind label"):
                labeled_file.parent.mkdir(parents=True, exist_ok=True)
                fresh = not labeled_file.exists()
                with labeled_file.open("a", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["episode", "start", "end", "note"])
                    if fresh:
                        writer.writeheader()
                    writer.writerow({"episode": episode["number"], "start": beats[start_index]["start"],
                                     "end": beats[end_index]["end"], "note": note})
                st.success("Label saved.")
    else:
        st.info("Upload a ZIP in the Run tab to use labels on Streamlit Cloud.")

with tabs[6]:
    st.subheader("Compare models")
    runs = []
    for path in Path(config["OUTPUT_DIR"]).glob("model_runs/*.json"):
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("complete") and run.get("provider") != "mock" and run.get("model") != "heuristics-only":
            runs.append(path)
    if len(runs) >= 2:
        names = st.multiselect("Runs", runs, format_func=lambda p: p.stem, default=runs[:2])
        if len(names) == 2:
            left, right = [json.loads(p.read_text(encoding="utf-8")) for p in names]
            overlap = len(set(left["ids"]) & set(right["ids"]))
            common = sorted(set(left["ids"]) & set(right["ids"]))
            n = len(common)
            if n > 1:
                left_ranks = {item: index + 1 for index, item in enumerate(
                    sorted(common, key=left["ids"].index))}
                right_ranks = {item: index + 1 for index, item in enumerate(
                    sorted(common, key=right["ids"].index))}
                distance = sum((left_ranks[item] - right_ranks[item]) ** 2 for item in common)
                correlation = 1 - 6 * distance / (n * (n * n - 1))
            else:
                correlation = None
            st.write({"left_model": left.get("model"), "right_model": right.get("model"),
                      "top_n_overlap": overlap, "left_only": sorted(set(left["ids"]) - set(right["ids"])),
                      "right_only": sorted(set(right["ids"]) - set(left["ids"])),
                      "rank_correlation": correlation})
    else:
        st.info("Run and save at least two model comparisons to view overlap.")

with tabs[7]:
    st.subheader("About")
    st.write("This tool ranks timestamped screenplay moments. It does not edit video.")
    st.write(f"Version {__version__}")
    st.write("The final clip choice and timing need a human review.")
    st.write("Known limits: screenplay time may differ from finished video time.")
    assumptions = Path("ASSUMPTIONS.md")
    if assumptions.exists():
        st.markdown(assumptions.read_text(encoding="utf-8"))
    st.link_button("GitHub repository", "https://github.com/elprofessor-15/KukuFM")
