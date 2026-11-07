import json
from pathlib import Path


def read_run() -> dict[str, str]:
    values = {}
    for line in Path("outputs/run_report.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("- ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            values[key] = value
    return values


def main():
    values = read_run()
    smoke_path = Path("outputs/smoke_results.json")
    smoke = json.loads(smoke_path.read_text(encoding="utf-8")) if smoke_path.exists() else []
    labels = Path("eval/labels.csv")
    label_rows = sum(1 for _ in labels.open(encoding="utf-8")) - 1 if labels.exists() else 0
    checks_path = Path("eval/auto_checks.json")
    checks = json.loads(checks_path.read_text(encoding="utf-8")) if checks_path.exists() else {}
    ablation_path = Path("eval/ablation.json")
    ablation = json.loads(ablation_path.read_text(encoding="utf-8")) if ablation_path.exists() else {}
    stability_path = Path("eval/stability.json")
    stability = json.loads(stability_path.read_text(encoding="utf-8")) if stability_path.exists() else {}
    failures_path = Path("eval/failure_candidates.md")
    failures = sum(line.startswith("- ") for line in failures_path.read_text(encoding="utf-8").splitlines()) \
        if failures_path.exists() else 0
    episodes = int(values.get("episodes_parsed", 0))
    tokens = int(values.get("measured_total_tokens",
                            int(values.get("tokens_input", 0)) + int(values.get("tokens_output", 0))))
    current_tokens = int(values.get("tokens_input", 0)) + int(values.get("tokens_output", 0))
    smoke_groups = {}
    for row in smoke:
        group = smoke_groups.setdefault(row["model"], {"json": 0, "quotes": 0, "timestamps": 0, "total": 0})
        group["json"] += bool(row["json_valid"])
        group["quotes"] += bool(row["quote_accurate"])
        group["timestamps"] += bool(row["timestamp_accurate"])
        group["total"] += 1
    lines = ["# Evaluation report", "",
             f'- Run id: {values.get("run_id", "not available")}',
             f'- Provider: {values.get("provider", "not available")}',
             f'- Model: {values.get("model", "not available")}',
             f'- Parsed episodes: {values.get("episodes_parsed", "not available")}',
             f'- Ranked promos: {values.get("promos_ranked", "not available")}',
             f'- Rejected promos: {values.get("promos_rejected", "not available")}',
             f'- Input tokens: {values.get("tokens_input", "not available")}',
             f'- Output tokens: {values.get("tokens_output", "not available")}',
             f'- Initial full live pass tokens: '
             f'{int(values.get("initial_live_tokens_input", 0)) + int(values.get("initial_live_tokens_output", 0))}',
             f'- Initial full live pass stage issue: {values.get("initial_live_failed_stages", "not recorded")}',
             f'- Current run tokens: {current_tokens}',
             f'- Unsafe model responses omitted from raw outputs: '
             f'{values.get("unsafe_responses_omitted_from_raw", "not available")}',
             f'- Estimated cost: {values.get("estimated_cost", "not available")}',
             f'- Runtime seconds: {values.get("runtime_seconds", "not available")}',
             f'- Initial live run stage error: {values.get("initial_live_failed_stages", "not recorded")}',
             f'- Initial live run duration seconds: {values.get("initial_live_runtime_seconds", "not recorded")}',
             f'- Total measured tokens: {tokens}',
             f'- Mean measured tokens per episode: {tokens / episodes:.2f}' if episodes else
             '- Mean measured tokens per episode: not available',
             f'- Ten-show token projection at this run size: {tokens * 10}',
             f'- Blind label rows: {label_rows}',
             '- Labels pending: fewer than 8 blind labels.' if label_rows < 8 else '- Labels pending: no.',
             f'- Suspicious promos listed for review: {failures}', "",
             "## Automated quality checks"]
    for key, item in checks.items():
        rate = f' ({item["rate"]:.3f})' if item["rate"] is not None else ""
        lines.append(f'- {key}: {item["count"]}/{item["total"]}{rate}')
    lines.extend(["", "## Three-episode model smoke"])
    for model, result in smoke_groups.items():
        lines.append(f'- {model}: JSON {result["json"]}/{result["total"]}, '
                     f'quotes {result["quotes"]}/{result["total"]}, '
                     f'timestamps {result["timestamps"]}/{result["total"]}')
    if ablation:
        lines.extend(["", "## Five-episode ablation"])
        lines.extend(f'- {key}: {value}' for key, value in ablation.items())
    if stability:
        lines.extend(["", "## Model stability"])
        lines.extend(f'- {key}: {value}' for key, value in stability.items())
    lines.extend(["", "I do not infer human quality from model scores. I use blind labels when available."])
    Path("eval/report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
