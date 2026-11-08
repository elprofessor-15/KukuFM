from __future__ import annotations

import argparse
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, Paragraph


INK = HexColor("#172033")
MUTED = HexColor("#566176")
PINK = HexColor("#ED4D7A")
PALE = HexColor("#FFF1F5")
LINE = HexColor("#DDE2EA")
WHITE = HexColor("#FFFFFF")


def paragraph(text: str, style: ParagraphStyle, frame: Frame, canvas_: canvas.Canvas) -> float:
    paragraphs = Paragraph(text, style)
    width, height = paragraphs.wrap(frame._width, frame._height)
    if height > frame._height:
        raise ValueError("PDF content overflowed the page frame.")
    paragraphs.drawOn(canvas_, frame._x1, frame._y2 - height)
    frame._y2 -= height
    return height


def heading(text: str, canvas_: canvas.Canvas, y: float, width: float) -> float:
    canvas_.setFillColor(INK)
    canvas_.setFont("Helvetica-Bold", 13)
    canvas_.drawString(46, y, text)
    canvas_.setStrokeColor(PINK)
    canvas_.setLineWidth(2)
    canvas_.line(46, y - 8, 46 + 32, y - 8)
    return y - 22


def footer(canvas_: canvas.Canvas, page: int) -> None:
    canvas_.setStrokeColor(LINE)
    canvas_.setLineWidth(0.5)
    canvas_.line(46, 34, 566, 34)
    canvas_.setFillColor(MUTED)
    canvas_.setFont("Helvetica", 8)
    canvas_.drawString(46, 20, "Kuku AI Generalist Assignment | Problem 1")
    canvas_.drawRightString(566, 20, str(page))


def draw_page_one(canvas_: canvas.Canvas) -> None:
    canvas_.setTitle("KukuFM PromoFinder Solution")
    canvas_.setAuthor("Abhineeth C")
    canvas_.setFillColor(INK)
    canvas_.rect(0, 684, 612, 108, fill=1, stroke=0)
    canvas_.setFillColor(PINK)
    canvas_.rect(46, 768, 40, 4, fill=1, stroke=0)
    canvas_.setFillColor(WHITE)
    canvas_.setFont("Helvetica-Bold", 26)
    canvas_.drawString(46, 716, "KukuFM PromoFinder")
    canvas_.setFont("Helvetica", 12)
    canvas_.drawString(46, 694, "Problem 1: Find the Promos")

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.8,
        leading=12.1, textColor=INK, spaceAfter=0)
    small = ParagraphStyle(
        "small", parent=body, fontSize=8, leading=10.7, textColor=MUTED)
    card = ParagraphStyle(
        "card", parent=body, fontSize=8.7, leading=11.5, leftIndent=8, rightIndent=8,
        spaceBefore=4, spaceAfter=4)

    y = 652
    y = heading("Problem choice and approach", canvas_, y, 520)
    text = (
        "I built a prototype that turns timestamped screenplay episodes into ranked, "
        "reviewable promo candidates. It is designed around three tests: a new viewer "
        "must understand the moment, the opening must create urgency in the first "
        "three seconds, and the end must leave a question unresolved."
    )
    p = Paragraph(text, body)
    w, h = p.wrap(520, 100)
    p.drawOn(canvas_, 46, y - h)
    y -= h + 18

    y = heading("How the system works", canvas_, y, 520)
    stages = [
        ("01", "Parse", "Read episode files and timestamped beats."),
        ("02", "Generate", "Create candidate windows of 20 to 60 seconds."),
        ("03", "Score", "Rank hooks, cliffhangers, clarity, and spoiler risk."),
        ("04", "Validate", "Check duration, quotes, beat boundaries, and overlap."),
        ("05", "Review", "Let an editor accept, reject, or nudge every result."),
    ]
    x = 46
    box = 99
    gap = 6
    for number, name, detail in stages:
        canvas_.setFillColor(PALE if number in ("03", "04") else HexColor("#F6F7F9"))
        canvas_.roundRect(x, y - 68, box, 68, 8, fill=1, stroke=0)
        canvas_.setFillColor(PINK)
        canvas_.setFont("Helvetica-Bold", 8)
        canvas_.drawString(x + 8, y - 18, number)
        canvas_.setFillColor(INK)
        canvas_.setFont("Helvetica-Bold", 9)
        canvas_.drawString(x + 8, y - 34, name)
        d = Paragraph(detail, small)
        dw, dh = d.wrap(box - 16, 34)
        d.drawOn(canvas_, x + 8, y - 58)
        x += box + gap
    y -= 92

    y = heading("Evidence from real runs", canvas_, y, 520)
    metrics = [
        ("50", "episodes parsed"),
        ("300", "candidates generated"),
        ("30", "promos ranked"),
        ("15.4s", "heuristic run time"),
    ]
    x = 46
    for value, label in metrics:
        canvas_.setFillColor(HexColor("#F6F7F9"))
        canvas_.roundRect(x, y - 48, 124, 48, 8, fill=1, stroke=0)
        canvas_.setFillColor(INK)
        canvas_.setFont("Helvetica-Bold", 16)
        canvas_.drawCentredString(x + 62, y - 20, value)
        canvas_.setFillColor(MUTED)
        canvas_.setFont("Helvetica", 7.5)
        canvas_.drawCentredString(x + 62, y - 37, label)
        x += 132
    y -= 68

    y = heading("What is automated and what stays human", canvas_, y, 520)
    text = (
        "<b>Code owns:</b> file parsing, candidate timing, duration checks, beat-edge "
        "snapping, exact quote verification, overlap rejection, exports, and repeatable runs. "
        "<b>AI assists:</b> compact candidate judgments when configured. "
        "<b>The editor owns:</b> cultural fit, social appeal, final cuts, and accept or reject decisions."
    )
    p = Paragraph(text, body)
    w, h = p.wrap(520, 100)
    p.drawOn(canvas_, 46, y - h)
    footer(canvas_, 1)
    canvas_.showPage()


def draw_page_two(canvas_: canvas.Canvas) -> None:
    canvas_.setFillColor(INK)
    canvas_.rect(0, 684, 612, 108, fill=1, stroke=0)
    canvas_.setFillColor(PINK)
    canvas_.rect(46, 768, 40, 4, fill=1, stroke=0)
    canvas_.setFillColor(WHITE)
    canvas_.setFont("Helvetica-Bold", 22)
    canvas_.drawString(46, 716, "Quality, scale, and honest limits")
    canvas_.setFont("Helvetica", 11)
    canvas_.drawString(46, 694, "Measured evidence and next release checks")

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.8,
        leading=12.1, textColor=INK)
    small = ParagraphStyle(
        "small", parent=body, fontSize=7.8, leading=10.5, textColor=MUTED)

    y = 652
    y = heading("Quality checks and observed results", canvas_, y, 520)
    rows = [
        ("30 / 30", "promos passed duration, quote, boundary, and validation checks"),
        ("52 / 52", "automated tests passed"),
        ("98 / 100", "full-pack preflight health; one sound block exceeded its scene"),
        ("2 / 9", "model smoke judgments matched exact source quote evidence"),
    ]
    for value, label in rows:
        canvas_.setFillColor(HexColor("#F6F7F9"))
        canvas_.roundRect(46, y - 38, 520, 34, 6, fill=1, stroke=0)
        canvas_.setFillColor(PINK)
        canvas_.setFont("Helvetica-Bold", 10)
        canvas_.drawString(58, y - 25, value)
        canvas_.setFillColor(INK)
        canvas_.setFont("Helvetica", 8.5)
        canvas_.drawString(112, y - 25, label)
        y -= 41
    y -= 5

    y = heading("Known failures", canvas_, y, 520)
    text = (
        "A rule-valid candidate is not guaranteed to be a good promo. A first line can be "
        "grammatically strong while the visual action lacks urgency. The first full live "
        "run also stopped at global ranking with a code error. It was not used as a "
        "completed AI ranking. The smallest repeatable sample and the full heuristic run "
        "are published separately, and cold-viewer labels are not claimed as completed."
    )
    p = Paragraph(text, body)
    w, h = p.wrap(520, 100)
    p.drawOn(canvas_, 46, y - h)
    y -= h + 18

    y = heading("How it scales", canvas_, y, 520)
    text = (
        "A show is processed episode by episode with bounded LLM calls and resumable cache. "
        "A new show needs only its screenplay files. Provider and model names are configuration. "
        "At production volume, I would add a worker queue, object storage, per-show isolation, "
        "editor feedback labels, and a publishing review gate. The current heuristic run cost "
        "was 0 because it used no paid provider calls."
    )
    p = Paragraph(text, body)
    w, h = p.wrap(520, 100)
    p.drawOn(canvas_, 46, y - h)
    y -= h + 18

    y = heading("AI tooling and one observed mistake", canvas_, y, 520)
    text = (
        "Tools used: Python, Streamlit, FastAPI, Groq, Vercel, GitHub, Pytest, and ReportLab. "
        "One observed model error was valid JSON and plausible timestamps paired with changed "
        "screenplay wording. The exact quote verifier rejected it. This is why the final evidence "
        "checks remain outside the model."
    )
    p = Paragraph(text, body)
    w, h = p.wrap(520, 100)
    p.drawOn(canvas_, 46, y - h)
    y -= h + 18

    y = heading("Submission links", canvas_, y, 520)
    canvas_.setFillColor(HexColor("#F6F7F9"))
    canvas_.roundRect(46, y - 74, 520, 74, 8, fill=1, stroke=0)
    canvas_.setFillColor(INK)
    canvas_.setFont("Helvetica-Bold", 8.5)
    canvas_.drawString(58, y - 24, "Prototype")
    canvas_.setFont("Helvetica", 8)
    canvas_.drawString(58, y - 38, "https://kukufm-promofinder-live.vercel.app")
    canvas_.setFont("Helvetica-Bold", 8.5)
    canvas_.drawString(58, y - 52, "Repository")
    canvas_.setFont("Helvetica", 8)
    canvas_.drawString(58, y - 66, "https://github.com/elprofessor-15/KukuFM")
    footer(canvas_, 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/solution_doc.pdf")
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(target), pagesize=letter)
    draw_page_one(pdf)
    draw_page_two(pdf)
    pdf.save()
    pages = len(PdfReader(str(target)).pages)
    if pages != 2:
        raise SystemExit(f"Expected 2 PDF pages, produced {pages}.")
    print(f"PDF has {pages} pages: {target}")


if __name__ == "__main__":
    main()
