"""Render an analyst-authored JSON report to an offline, searchable PDF.

No network access, code evaluation or business inference is performed here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, LongTable, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

INK = colors.HexColor("#17324D")
TEAL = colors.HexColor("#087E8B")
ORANGE = colors.HexColor("#BE592B")
MUTED = colors.HexColor("#526475")
PALE = colors.HexColor("#EDF4F7")
FONT = "ReportFont"
WIDTH = A4[0] - 36 * mm


def require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def require_list(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")


def validate_report(report):
    if not isinstance(report, dict):
        raise ValueError("Report must be an object")
    require_text(report.get("title"), "title")
    if "subtitle" in report:
        require_text(report["subtitle"], "subtitle")
    for key in ("summary", "sources"):
        if key in report:
            require_list(report[key], key)
            for value in report[key]:
                require_text(value, key)
    sections = report.get("sections")
    require_list(sections, "sections")
    if not sections:
        raise ValueError("At least one section is required")
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("Each section must be an object")
        require_text(section.get("title"), "section.title")
        if "page_break" in section and not isinstance(section["page_break"], bool):
            raise ValueError("page_break must be a boolean")
        for key in ("paragraphs", "bullets"):
            if key in section:
                require_list(section[key], key)
                for value in section[key]:
                    require_text(value, key)
        if "table" in section:
            table = section["table"]
            if not isinstance(table, dict):
                raise ValueError("table must be an object")
            columns, rows = table.get("columns"), table.get("rows")
            require_list(columns, "table.columns")
            if not 1 <= len(columns) <= 8:
                raise ValueError("Tables need 1 to 8 columns; split wider tables")
            for column in columns:
                require_text(column, "table.columns")
            require_list(rows, "table.rows")
            for row in rows:
                if not isinstance(row, list) or len(row) != len(columns):
                    raise ValueError("Each table row must match column count")
                for value in row:
                    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                        raise ValueError("Table cells must be strings or finite numbers")
                    if isinstance(value, (int, float)) and not math.isfinite(value):
                        raise ValueError("Table cells cannot contain NaN or infinity")
        if "chart" in section:
            chart = section["chart"]
            if not isinstance(chart, dict):
                raise ValueError("chart must be an object")
            for key in ("title", "unit", "source"):
                require_text(chart.get(key), f"chart.{key}")
            labels, values = chart.get("labels"), chart.get("values")
            require_list(labels, "chart.labels")
            require_list(values, "chart.values")
            if not labels or len(labels) != len(values):
                raise ValueError("Chart labels and values must be non-empty and equal length")
            for label in labels:
                require_text(label, "chart.labels")
            for value in values:
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)):
                    raise ValueError("Chart values must be finite numbers, not missing values")
        if "image" in section:
            image = section["image"]
            if not isinstance(image, dict):
                raise ValueError("image must be an object")
            for key in ("path", "caption", "source"):
                require_text(image.get(key), f"image.{key}")
            if "://" in image["path"]:
                raise ValueError("Only local image paths are supported")
    return report


def select_font(explicit=None):
    """Prefer an embedded TrueType CJK font, never a remote font download."""
    # Proportional CJK faces render ASCII digits/punctuation tightly; the
    # monospaced-style faces (simsun, simhei) leave wide gaps inside numbers.
    candidates = [explicit] if explicit else [
        os.environ.get("AMAZON_ANALYST_FONT"),
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/Deng.ttf",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    failures = []
    for candidate in filter(None, candidates):
        path = Path(candidate).expanduser()
        if not path.is_file():
            failures.append(f"{path.name}: not found")
            continue
        try:
            pdfmetrics.registerFont(TTFont(FONT, str(path), subfontIndex=0))
            return path
        except Exception as exc:
            failures.append(f"{path.name}: {type(exc).__name__}")
    raise ValueError(
        "No usable CJK TrueType font. Pass --font /path/to/font.ttf (or .ttc). "
        "CFF-outline fonts are not supported by this renderer. " + "; ".join(failures)
    )


def has_cjk(text):
    return any("㐀" <= ch <= "鿿" or "豈" <= ch <= "﫿" for ch in str(text))


def pick(styles, value, latin_key, cjk_key):
    """Pure ASCII/numeric cells wrap LTR so narrow columns never split a number."""
    return styles[latin_key] if not has_cjk(value) else styles[cjk_key]


def make_styles():
    base = dict(fontName=FONT, textColor=INK, wordWrap="CJK", leading=17)
    return {
        "cell_latin": ParagraphStyle("CellLatin", fontSize=9, leading=14, fontName=FONT,
                                     textColor=INK, wordWrap="LTR"),
        "head_latin": ParagraphStyle("TableHeadLatin", fontSize=9, leading=14, fontName=FONT,
                                     textColor=colors.white, wordWrap="LTR"),
        "title": ParagraphStyle("Title", fontSize=24, leading=32, spaceAfter=12, **{
            k: v for k, v in base.items() if k != "leading"}),
        "subtitle": ParagraphStyle("Subtitle", fontSize=10, spaceAfter=16, **base),
        "h1": ParagraphStyle("Heading", fontSize=15, spaceBefore=14,
                             spaceAfter=9, keepWithNext=True, **base),
        "body": ParagraphStyle("Body", fontSize=10.5, spaceAfter=9, **base),
        "small": ParagraphStyle("Small", fontSize=8.5, leading=13,
                                textColor=MUTED, fontName=FONT, wordWrap="CJK", spaceAfter=6),
        "cell": ParagraphStyle("Cell", fontSize=9, leading=14, fontName=FONT,
                               textColor=INK, wordWrap="CJK"),
        "head": ParagraphStyle("TableHead", fontSize=9, leading=14, fontName=FONT,
                               textColor=colors.white, wordWrap="CJK"),
    }


def para(value, style):
    # Plain text only: report content cannot inject ReportLab markup or links.
    return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)


def make_table(table, styles):
    columns = table["columns"]
    rows = [[para(c, pick(styles, c, "head_latin", "head")) for c in columns]]
    rows += [[para(c, pick(styles, c, "cell_latin", "cell")) for c in row]
             for row in table["rows"]]
    result = LongTable(rows, colWidths=[WIDTH / len(columns)] * len(columns),
                       repeatRows=1, hAlign="LEFT", splitByRow=1)
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, INK),
    ]))
    return result


def make_chart(chart, styles):
    low = min(0, *chart["values"])
    high = max(0, *chart["values"])
    span = high - low or 1
    plot_width = WIDTH * 0.55 - 12
    zero = -low / span * plot_width
    rows = []
    for label, value in zip(chart["labels"], chart["values"]):
        drawing = Drawing(plot_width, 23)
        endpoint = (value - low) / span * plot_width
        drawing.add(Line(zero, 1, zero, 22, strokeColor=MUTED, strokeWidth=0.6))
        if value:
            drawing.add(Rect(min(zero, endpoint), 4, abs(endpoint - zero), 15,
                             fillColor=TEAL if value >= 0 else ORANGE, strokeColor=None))
        rows.append([para(label, pick(styles, label, "cell_latin", "cell")), drawing,
                     para(f"{value:,.2f}", styles["cell_latin"])])
    table = Table(rows, colWidths=[WIDTH * 0.27, WIDTH * 0.55, WIDTH * 0.18])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    # Keep only caption with the first row; allow longer charts to continue on another page.
    return [para(chart["title"] + "（" + chart["unit"] + "）", styles["body"]),
            table, para("来源：" + chart["source"], styles["small"])]


def render_report(report, output, font=None, base_dir=None):
    validate_report(report)
    select_font(font)
    styles = make_styles()
    base_dir = Path(base_dir or ".").resolve()
    output = Path(output)
    # Resolve and verify all external assets before creating the final output.
    images = {}
    for index, section in enumerate(report["sections"]):
        if "image" in section:
            path = Path(section["image"]["path"])
            path = path if path.is_absolute() else base_dir / path
            path = path.resolve()
            if not path.is_file():
                raise ValueError(f"Image file not found: {path.name}")
            images[index] = path
    story = [para(report["title"], styles["title"])]
    if report.get("subtitle"):
        story.append(para(report["subtitle"], styles["subtitle"]))
    if report.get("summary"):
        story.append(para("决策摘要", styles["h1"]))
        story += [para(f"{i}. {text}", styles["body"])
                  for i, text in enumerate(report["summary"], 1)]
    for index, section in enumerate(report["sections"]):
        if section.get("page_break"):
            story.append(PageBreak())
        story.append(para(section["title"], styles["h1"]))
        story += [para(text, styles["body"]) for text in section.get("paragraphs", [])]
        story += [para(f"{i}. {text}", styles["body"])
                  for i, text in enumerate(section.get("bullets", []), 1)]
        if "table" in section:
            story.extend([make_table(section["table"], styles), Spacer(1, 10)])
        if "chart" in section:
            story.extend(make_chart(section["chart"], styles))
        if "image" in section:
            im = Image(str(images[index]))
            ratio = min(WIDTH / im.imageWidth, 155 * mm / im.imageHeight, 1)
            im.drawWidth, im.drawHeight = im.imageWidth * ratio, im.imageHeight * ratio
            story.append(KeepTogether([
                im, para(section["image"]["caption"], styles["small"]),
                para("来源：" + section["image"]["source"], styles["small"]),
            ]))
    if report.get("sources"):
        story.append(para("数据与计算说明", styles["h1"]))
        story += [para(text, styles["small"]) for text in report["sources"]]

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D9E3EA"))
        canvas.line(18 * mm, 17 * mm, A4[0] - 18 * mm, 17 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(FONT, 8)
        canvas.drawString(18 * mm, 12 * mm, "Amazon Business Analyst")
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    output.parent.mkdir(parents=True, exist_ok=True)
    # A failed layout should not leave a misleading, partial deliverable.
    import tempfile
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".pdf", delete=False) as stream:
        temp = Path(stream.name)
    try:
        doc = SimpleDocTemplate(str(temp), pagesize=A4, rightMargin=18 * mm,
                                leftMargin=18 * mm, topMargin=19 * mm,
                                bottomMargin=24 * mm, title=report["title"],
                                author="Amazon Business Analyst")
        doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
        temp.replace(output)
    finally:
        if temp.exists():
            temp.unlink()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Report JSON file (UTF-8)")
    parser.add_argument("output", type=Path, help="Destination PDF")
    parser.add_argument("--font", type=Path, help="CJK TrueType .ttf or .ttc font")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output paths must differ")
    try:
        report = json.loads(args.input.read_text(encoding="utf-8-sig"))
        result = render_report(report, args.output, args.font, args.input.parent)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(f"Created: {result}")


if __name__ == "__main__":
    main()
