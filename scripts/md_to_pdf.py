"""Convert a (CJK-friendly) markdown report to PDF using fpdf2.

Only supports the small subset of markdown produced by build_report.py:
headings (#/##/###), horizontal rules (---), bold (**text**), pipe tables,
image references (![alt](path)), and plain paragraphs/bullets.

Usage:
    python3 md_to_pdf.py <report.md> <report.pdf> [--font /path/to/font.ttc]

Font resolution order if --font is not given:
    1. $SECURITY_SCAN_CJK_FONT env var
    2. A handful of common Linux system paths
    3. `fc-match` query result (if fontconfig is installed)
    4. Common WSL-mounted Windows locations (e.g. bundled with some IDEs)
If none are found, exits with a clear error explaining how to fix it.
See references/pitfalls.md for why this is needed and for a known fpdf2
cursor-position bug this script works around.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

from fpdf import FPDF

EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]+"
)

CANDIDATE_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "/mnt/c/Program Files/Android/Android Studio/plugins/design-tools/resources/layoutlib/data/fonts/NotoSansCJK-Regular.ttc",
]


def find_cjk_font() -> str:
    env_path = os.environ.get("SECURITY_SCAN_CJK_FONT")
    if env_path and os.path.isfile(env_path):
        return env_path

    for path in CANDIDATE_FONT_PATHS:
        if os.path.isfile(path):
            return path

    if shutil.which("fc-match"):
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}", "Noto Sans CJK SC"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if out and os.path.isfile(out):
                return out
        except Exception:
            pass

    raise SystemExit(
        "No CJK-capable font found. Set SECURITY_SCAN_CJK_FONT to a .ttc/.ttf "
        "path that covers CJK glyphs (e.g. Noto Sans CJK), or install one "
        "(e.g. `fonts-noto-cjk` via apt) and re-run."
    )


def build_pdf(md_path: str, pdf_path: str, font_path: str) -> None:
    md_dir = os.path.dirname(os.path.abspath(md_path))
    with open(md_path, encoding="utf-8") as f:
        raw_lines = f.read().splitlines()
    lines = [EMOJI_PATTERN.sub("", line).rstrip() for line in raw_lines]

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("Body", "", font_path)
    pdf.add_font("Body", "B", font_path)
    pdf.set_font("Body", "", 11)

    def para(text, size=11, style="", gap=6):
        pdf.set_font("Body", style, size)
        # A table rendered just before this can leave the x cursor mid-page;
        # multi_cell() then has ~0 width left and throws. See pitfalls.md #5.
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, gap, text)

    table_rows: list[str] = []
    in_table = False

    def flush_table():
        nonlocal table_rows, in_table
        rows = [r for r in table_rows if not re.match(r"^\|[\s:|-]+\|$", r)]
        table_rows = []
        in_table = False
        if not rows:
            return
        raw_cells = [r.strip().strip("|").split("|") for r in rows]
        parsed = [[re.sub(r"\*\*(.*?)\*\*", r"\1", c.strip()) for c in row] for row in raw_cells]
        ncols = max(len(r) for r in parsed)
        page_width = pdf.w - pdf.l_margin - pdf.r_margin
        col_width = page_width / ncols
        for i, row in enumerate(parsed):
            pdf.set_x(pdf.l_margin)
            is_bold_row = i == 0 or any("**" in c for c in raw_cells[i])
            pdf.set_font("Body", "B" if is_bold_row else "", 9)
            for cell in row:
                pdf.cell(col_width, 8, cell, border=1)
            pdf.ln(8)
        pdf.ln(4)
        pdf.set_x(pdf.l_margin)

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("|"):
            table_rows.append(stripped)
            in_table = True
            continue
        if in_table:
            flush_table()

        img_match = re.match(r"^!\[.*?\]\((.+?)\)$", stripped)

        if not stripped:
            pdf.ln(3)
        elif img_match:
            img_path = img_match.group(1)
            if not os.path.isabs(img_path):
                img_path = os.path.join(md_dir, img_path)
            if os.path.isfile(img_path):
                pdf.set_x(pdf.l_margin)
                page_width = pdf.w - pdf.l_margin - pdf.r_margin
                pdf.image(img_path, x=pdf.l_margin, w=page_width)
                pdf.ln(4)
        elif stripped.startswith("#### "):
            para(stripped[5:], size=12, style="B", gap=7)
        elif stripped.startswith("### "):
            para(stripped[4:], size=13, style="B", gap=8)
        elif stripped.startswith("## "):
            para(stripped[3:], size=15, style="B", gap=9)
        elif stripped.startswith("# "):
            para(stripped[2:], size=18, style="B", gap=10)
        elif stripped == "---":
            pdf.ln(2)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(4)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            clean = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped[2:])
            para(f"• {clean}", size=11)
        elif stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            para(stripped.strip("*"), size=11, style="B")
        else:
            clean = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped)
            para(clean, size=11)

    if in_table:
        flush_table()

    pdf.output(pdf_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("md_path")
    parser.add_argument("pdf_path")
    parser.add_argument("--font", help="Path to a CJK-capable .ttc/.ttf font")
    args = parser.parse_args()

    font_path = args.font or find_cjk_font()
    build_pdf(args.md_path, args.pdf_path, font_path)
    print(f"wrote {args.pdf_path} (font: {font_path})")


if __name__ == "__main__":
    main()
