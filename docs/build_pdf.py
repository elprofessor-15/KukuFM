from __future__ import annotations

import argparse
from pathlib import Path
import textwrap

from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def bullet_values(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            values[key] = value
    return values


def section_text(source: str, heading: str) -> list[str]:
    lines = source.splitlines()
    start = next((index + 1 for index, line in enumerate(lines) if line == heading), None)
    if start is None:
        return []
    result = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.strip():
            result.append(line.removeprefix("- ").replace("**", ""))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--output", default="docs/solution_doc.pdf")
    args = parser.parse_args()
    source = Path("docs/solution_doc.md").read_text(encoding="utf-8")
    if "[WRITE THIS YOURSELF" in source and not args.draft:
        raise SystemExit("Final PDF refused: replace every [WRITE THIS YOURSELF marker first.")
    run_path = Path("outputs/run_report.md")
    run = bullet_values(run_path)
    evaluation_path = Path("eval/report.md")
    evaluation = bullet_values(evaluation_path)
    try:
        total_tokens = int(run.get("measured_total_tokens",
                                   int(run.get("tokens_input", 0)) + int(run.get("tokens_output", 0))))
        current_tokens = int(run.get("tokens_input", 0)) + int(run.get("tokens_output", 0))
        initial_tokens = int(run.get("initial_live_tokens_input", 0)) + \
            int(run.get("initial_live_tokens_output", 0))
        episodes = int(run.get("episodes_parsed", 0))
        cost = float(run.get("estimated_cost", 0)) + float(run.get("initial_live_estimated_cost", 0))
    except ValueError as exc:
        raise SystemExit("Run report contains invalid numeric values.") from exc
    lines = ["KukuFM PromoFinder solution", "", "I rank screenplay moments for editor review.",
             "Problem: I rank 20 to 60 second screenplay moments with an early hook and unresolved ending.",
             "Pipeline:",
             "", "Assumptions: screenplay timestamps align with video. An editor checks every boundary.",
             "AI judges compact excerpts. Code parses files and validates quotes, beat edges, and duration.",
             f'Run: {run.get("episodes_parsed", "not available")} episodes, '
             f'{run.get("promos_ranked", "not available")} promos, '
             f'{run.get("promos_rejected", "not available")} rejected.',
             f'Tokens: initial live pass {initial_tokens}, current run {current_tokens}, '
             f'{total_tokens} measured total.',
             f'Average per episode: {evaluation.get("Mean measured tokens per episode", "not available")} tokens. '
             f'Ten-show projection: {total_tokens * 10} tokens.',
             f'Configured cost estimate: ${cost:.4f} for this run, ${cost * 10:.4f} for ten similar shows. '
             "Price settings are not provider billing records.",
             f'Runtime: {run.get("runtime_seconds", "not available")} seconds.',
             "Quality results:"]
    for name in ("validity", "quote_verification", "duration_compliance", "snap_rate", "raw_proposal_validity",
                 "rejected_share", "cold_viewer_conflict_missing"):
        if name in evaluation:
            lines.append(f'{name}: {evaluation[name]}')
    lines.extend(["", "Blind labels: " + evaluation.get("Blind label rows", "0") + ".",
                  "Failures and tools:"])
    lines.extend(section_text(source, "## Failures") or
                 ["[WRITE THIS YOURSELF: Review the real candidates in eval/failure_candidates.md.]"])
    lines.append("Tools and one AI mistake:")
    lines.extend(section_text(source, "## Tools and one AI mistake") or
                 ["[WRITE THIS YOURSELF: Record tools used and one observed model error.]"])
    target = Path(args.output)
    target.parent.mkdir(exist_ok=True)
    pdf = canvas.Canvas(str(target), pagesize=letter)
    width, height = letter
    y = height - 48
    for line in lines:
        if line == "Pipeline:":
            labels = ["preflight", "parse", "windows", "scores", "editor"]
            box_width = 88
            gap = 18
            total_width = len(labels) * box_width + (len(labels) - 1) * gap
            x = (width - total_width) / 2
            box_y = y - 40
            for index, label in enumerate(labels):
                position = x + index * (box_width + gap)
                pdf.rect(position, box_y, box_width, 28)
                pdf.drawCentredString(position + box_width / 2, box_y + 10, label)
                if index < len(labels) - 1:
                    pdf.line(position + box_width, box_y + 14, position + box_width + gap, box_y + 14)
            y -= 70
            continue
        for wrapped in textwrap.wrap(line, width=88) or [""]:
            pdf.drawString(48, y, wrapped)
            y -= 13
            if y < 48:
                pdf.showPage()
                y = height - 48
    pdf.save()
    count = len(PdfReader(str(target)).pages)
    if count > 2:
        target.unlink()
        raise SystemExit(f"PDF has {count} pages, maximum is 2.")
    print(f"{'Draft ' if args.draft else ''}PDF has {count} page(s).")


if __name__ == "__main__":
    main()
