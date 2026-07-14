"""Convert a (CJK-friendly) markdown report to PDF using fpdf2.

Only supports the small subset of markdown produced by build_report.py:
headings (#/##/###), horizontal rules (---), bold (**text**), inline code
(`text`, rendered as plain text — fpdf2 has no second font to set it in
monospace, and keeping the backticks just reads as clutter), pipe tables,
image references (![alt](path)), blockquotes (> text, rendered as a smaller
plain paragraph), and plain paragraphs/bullets (nested bullets indented two
spaces per level render with a matching visual indent and hanging wrap).
Bold spans are rendered with fpdf2's own markdown=True (real bold face, not
just a bigger size), and each finding-title bullet in the classification/
manual-findings sections is colored by severity (see finding_title_color()).

Usage:
    python3 md_to_pdf.py <report.md> <report.pdf> [--font /path/to/font.ttc] [--font-bold /path/to/bold.ttc]

Font resolution order if --font is not given:
    1. $SECURITY_SCAN_CJK_FONT (+ optional $SECURITY_SCAN_CJK_FONT_BOLD) env vars
    2. A variable-weight CJK font (e.g. a WSL-mounted Noto Sans TC), instanced
       into static Regular/Bold weights on first use and cached under
       ~/.cache/security-scan-kit/fonts/ — this is what gives real bold
       headings instead of Regular reused under the "B" style
    3. find_cjk_font()'s existing candidates (common Linux paths / fc-match /
       WSL-mounted msyh.ttc), paired with a same-directory bold sibling
       (e.g. msyhbd.ttc) if one exists, else falling back to regular-as-bold
If none are found, exits with a clear error explaining how to fix it. None of
this is required for other environments: a machine without the variable font
just falls through to the same resolution this script always had.
See references/pitfalls.md for why this is needed and for a known fpdf2
cursor-position bug this script works around.
"""
import argparse
import hashlib
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

# Variable-weight fonts tried before falling back to CANDIDATE_FONT_PATHS —
# nicer for reading a formal report, and (being variable) let us bake out a
# genuine Bold instance instead of faking it. Only tried if the path exists;
# harmless on any machine that doesn't have it.
VARIABLE_FONT_CANDIDATES = [
    "/mnt/c/Windows/Fonts/NotoSansTC-VF.ttf",
]

# Known regular->bold sibling file pairs (same directory) for static (non-
# variable) font candidates, so headings get a real bold face rather than
# the regular glyphs stretched under the "B" style.
BOLD_SIBLINGS = {
    "msyh.ttc": "msyhbd.ttc",
    "NotoSansCJK-Regular.ttc": "NotoSansCJK-Bold.ttc",
}

FONT_CACHE_DIR = os.path.expanduser("~/.cache/security-scan-kit/fonts")


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


def _instance_static_weight(vf_path: str, wght: int) -> str:
    """Bake a static-weight instance out of a variable font, cached by path+weight
    so repeated report builds don't redo the instancing work."""
    key = hashlib.sha1(f"{vf_path}:{wght}".encode()).hexdigest()[:16]
    out_path = os.path.join(FONT_CACHE_DIR, f"{os.path.basename(vf_path)}.{wght}.{key}.ttf")
    if os.path.isfile(out_path):
        return out_path
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = TTFont(vf_path)
    instancer.instantiateVariableFont(font, {"wght": wght}, inplace=True)
    os.makedirs(FONT_CACHE_DIR, exist_ok=True)
    font.save(out_path)
    return out_path


def _try_variable_font_pair(vf_path: str):
    """Return (regular_path, bold_path) instanced from a variable font, or None
    if the path doesn't exist or instancing fails for any reason (missing
    fonttools support, corrupt font, ...) — callers fall back silently."""
    if not os.path.isfile(vf_path):
        return None
    try:
        return _instance_static_weight(vf_path, 400), _instance_static_weight(vf_path, 700)
    except Exception:
        return None


def _find_bold_sibling(regular_path: str):
    sibling = BOLD_SIBLINGS.get(os.path.basename(regular_path))
    if not sibling:
        return None
    candidate = os.path.join(os.path.dirname(regular_path), sibling)
    return candidate if os.path.isfile(candidate) else None


def resolve_report_fonts():
    """Resolve (regular_path, bold_path) for the report body font. See the
    module docstring for the fallback order; every step degrades to the next
    rather than raising, except the final find_cjk_font() call."""
    env_regular = os.environ.get("SECURITY_SCAN_CJK_FONT")
    if env_regular and os.path.isfile(env_regular):
        env_bold = os.environ.get("SECURITY_SCAN_CJK_FONT_BOLD")
        bold = env_bold if env_bold and os.path.isfile(env_bold) else (_find_bold_sibling(env_regular) or env_regular)
        return env_regular, bold

    for vf_path in VARIABLE_FONT_CANDIDATES:
        pair = _try_variable_font_pair(vf_path)
        if pair:
            return pair

    regular = find_cjk_font()
    return regular, (_find_bold_sibling(regular) or regular)


def strip_inline_markup(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text


def strip_code_markup(text: str) -> str:
    """Drop inline-code backticks but keep **bold** markers intact — those are
    rendered by fpdf2's own markdown=True, not manually stripped."""
    return re.sub(r"`(.*?)`", r"\1", text)


SEVERITY_RE = re.compile(r"嚴重度[：:]\s*([A-Za-z]+)")
CATEGORY_HEADING_RE = re.compile(r"^([A-D])\.\s")

COLOR_CRITICAL_HIGH = (183, 28, 28)
COLOR_MEDIUM = (217, 119, 6)
COLOR_MUTED = (128, 128, 128)
COLOR_DEFAULT = (0, 0, 0)


def finding_title_color(severity: str, is_false_positive: bool):
    """Findings unrelated to exploitable security risk (false positives, or
    Informational/Optimization impact) are muted gray regardless of their
    raw impact value; otherwise color follows severity."""
    if is_false_positive or severity in ("Informational", "Optimization"):
        return COLOR_MUTED
    if severity in ("Critical", "High"):
        return COLOR_CRITICAL_HIGH
    if severity == "Medium":
        return COLOR_MEDIUM
    return COLOR_DEFAULT


def build_pdf(md_path: str, pdf_path: str, font_path: str, bold_font_path: str = None) -> None:
    md_dir = os.path.dirname(os.path.abspath(md_path))
    with open(md_path, encoding="utf-8") as f:
        raw_lines = f.read().splitlines()
    # CJK fonts typically have no glyph for \t, and fpdf2 warns per character.
    lines = [EMOJI_PATTERN.sub("", line).replace("\t", " ").rstrip() for line in raw_lines]

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("Body", "", font_path)
    pdf.add_font("Body", "B", bold_font_path or font_path)
    pdf.set_font("Body", "", 11)

    def para(text, size=11, style="", gap=6, color=None):
        pdf.set_font("Body", style, size)
        # A table rendered just before this can leave the x cursor mid-page;
        # multi_cell() then has ~0 width left and throws. See pitfalls.md #5.
        pdf.set_x(pdf.l_margin)
        if color:
            pdf.set_text_color(*color)
        # fpdf2 defaults multi_cell() to JUSTIFY, which stretches gaps at the
        # few Latin-word space characters in otherwise-space-free CJK text
        # into huge visible gaps. Left-align instead. markdown=True renders
        # **bold** spans in the real bold face registered above instead of
        # them being stripped to plain text.
        pdf.multi_cell(0, gap, strip_code_markup(text), align="L", markdown=True)
        if color:
            pdf.set_text_color(*COLOR_DEFAULT)

    def bullet(text, indent_mm=0, size=11, gap=6, color=None):
        pdf.set_font("Body", "", size)
        # Draw the bullet marker in its own fixed cell and anchor the text in
        # a multi_cell right after it. A long space-free CJK sentence is one
        # "word" to fpdf2's line breaker: rendered as a single para("• …") it
        # gets pushed whole to the next line, stranding the bullet alone on
        # its own line. Anchoring the text cell also makes wrapped lines
        # continue under the text (hanging indent) instead of under the
        # bullet.
        pdf.set_x(pdf.l_margin + indent_mm)
        if color:
            pdf.set_text_color(*color)
        pdf.cell(5, gap, "•")
        pdf.multi_cell(0, gap, strip_code_markup(text), align="L", markdown=True)
        if color:
            pdf.set_text_color(*COLOR_DEFAULT)

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
        parsed = [[strip_inline_markup(c.strip()) for c in row] for row in raw_cells]
        ncols = max(len(r) for r in parsed)
        page_width = pdf.w - pdf.l_margin - pdf.r_margin
        col_width = page_width / ncols
        line_height = 5
        x0 = pdf.l_margin
        for i, row in enumerate(parsed):
            is_bold_row = i == 0 or any("**" in c for c in raw_cells[i])
            pdf.set_font("Body", "B" if is_bold_row else "", 9)
            # Wrap each cell's text first so long content (e.g. a "說明"
            # column) doesn't overflow past its column and overlap the next
            # one — pdf.cell() never wraps or clips, it just draws past its
            # nominal width. See pitfalls.md #5 for the related cursor bug.
            cell_lines = [
                pdf.multi_cell(col_width, line_height, cell, border=0, align="L", dry_run=True, output="LINES")
                or [""]
                for cell in row
            ]
            row_height = max(len(lines) for lines in cell_lines) * line_height
            if pdf.get_y() + row_height > pdf.page_break_trigger:
                pdf.add_page()
            y0 = pdf.get_y()
            for ci, cell in enumerate(row):
                x = x0 + ci * col_width
                pdf.rect(x, y0, col_width, row_height)
                pdf.set_xy(x, y0)
                pdf.multi_cell(col_width, line_height, cell, border=0, align="L")
            pdf.set_xy(x0, y0 + row_height)
        pdf.ln(4)
        pdf.set_x(pdf.l_margin)

    # Tracks which A/B/C/D classification section (§7) or manual-findings
    # section (§6) we're currently inside, so finding-title bullets can be
    # colored gray when they're category C (false positive) even though
    # their raw Slither impact might be High. Reset on every "## " (new major
    # section) and updated on every "### " category sub-heading.
    current_category = None

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
            heading_text = stripped[4:]
            m = CATEGORY_HEADING_RE.match(heading_text)
            current_category = m.group(1) if m else None
            para(heading_text, size=13, style="B", gap=8)
        elif stripped.startswith("## "):
            current_category = None
            para(stripped[3:], size=15, style="B", gap=9)
        elif stripped.startswith("# "):
            current_category = None
            para(stripped[2:], size=18, style="B", gap=10)
        elif stripped == "---":
            pdf.ln(2)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(4)
        elif stripped.startswith(">"):
            clean = stripped.lstrip(">").strip()
            if clean:
                para(clean, size=10)
            else:
                pdf.ln(3)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            # Nested list items (2 spaces per level in the markdown) get a
            # matching visual indent.
            depth = (len(line) - len(line.lstrip(" "))) // 2
            content = stripped[2:]
            color = None
            if depth == 0:
                # Only top-level bullets are finding titles (§6/§7); nested
                # sub-items (原始描述/工程註記 etc.) stay uncolored.
                sev_match = SEVERITY_RE.search(content)
                if sev_match:
                    color = finding_title_color(sev_match.group(1), current_category == "C")
            bullet(content, indent_mm=depth * 5, color=color)
        else:
            para(stripped, size=11)

    if in_table:
        flush_table()

    pdf.output(pdf_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("md_path")
    parser.add_argument("pdf_path")
    parser.add_argument("--font", help="Path to a CJK-capable regular-weight .ttc/.ttf font")
    parser.add_argument("--font-bold", help="Path to a CJK-capable bold-weight .ttc/.ttf font")
    args = parser.parse_args()

    if args.font:
        font_path = args.font
        bold_font_path = args.font_bold or _find_bold_sibling(args.font) or args.font
    else:
        font_path, bold_font_path = resolve_report_fonts()
    build_pdf(args.md_path, args.pdf_path, font_path, bold_font_path)
    print(f"wrote {args.pdf_path} (font: {font_path}, bold: {bold_font_path})")


if __name__ == "__main__":
    main()
