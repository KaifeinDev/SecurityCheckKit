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
       ~/.cache/security-check-kit/fonts/ — this is what gives real bold
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

FONT_CACHE_DIR = os.path.expanduser("~/.cache/security-check-kit/fonts")


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
BANNER_RE = re.compile(r"^\*\*【(.+?)】\*\*$")

# BSOS 文件規格設計系統 v1.0 — Gray 色階 (§2.1) 與 Colorful 色票 700 層級 (§2.2)。
# 700 是規格裡「淺底用同色相 700」的規定層級（表 3.6），比 500 更深、在白底上
# 對比度更夠，比 900 保留一點色相辨識度，不會看起來近乎黑色。
GRAY_50 = (250, 250, 250)
GRAY_100 = (244, 244, 245)
GRAY_200 = (228, 228, 231)
GRAY_300 = (212, 212, 216)
GRAY_400 = (161, 161, 170)
GRAY_500 = (113, 113, 122)
GRAY_600 = (82, 82, 91)
GRAY_700 = (63, 63, 70)
GRAY_800 = (39, 39, 42)
GRAY_900 = (24, 24, 27)

RED_100 = (251, 231, 229)
RED_700 = (142, 49, 40)
ORANGE_100 = (252, 237, 221)
ORANGE_700 = (143, 82, 16)
YELLOW_700 = (106, 87, 9)
BLUE_100 = (229, 237, 250)
BLUE_700 = (36, 72, 127)

COLOR_CRITICAL_HIGH = RED_700
COLOR_MEDIUM = ORANGE_700
COLOR_LOW = YELLOW_700
COLOR_MUTED = GRAY_500
COLOR_DEFAULT = GRAY_900
COLOR_HEADING = BLUE_700
COLOR_BANNER_BG = RED_100
COLOR_BANNER_TEXT = RED_700

# Designer-supplied cover background (assets/cover_template.png, rasterized
# from Untitled.svg — BSOS logo + hexagon/gradient-sphere decoration, A4 @
# 150dpi, 1240x1754px). The "檢測工具"/"檢測日期" value text from the
# designer's mockup was cut out (see cover_blanked crop step in dev history)
# so real values can be drawn on top at build time; the title and field
# labels are baked into the image since they're constant across reports.
COVER_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "cover_template.png")
_COVER_IMG_W, _COVER_IMG_H = 1240, 1754  # px, matches the asset above
# Bounding boxes measured directly off the 300dpi source render (2481x3509)
# by isolating non-background pixels per text row, then halved for the
# 150dpi asset — see dev history for the measurement script. Given in mm
# (A4 = 210x297mm) so they're resolution-independent of the asset itself.
COVER_TOOL_XY_MM = (699 * 210 / 2481, 1606 * 297 / 3509 - 0.3)
COVER_DATE_XY_MM = (699 * 210 / 2481, 1698 * 297 / 3509 - 0.3)
COVER_VALUE_ROW_H_MM = (1654 - 1606) * 297 / 3509 + 0.6
COVER_TITLE_RE = re.compile(r"^#\s+(.+)$")
COVER_TOOL_RE = re.compile(r"^\*\*檢測工具\*\*[:：]\s*(.+)$")
COVER_DATE_RE = re.compile(r"^\*\*檢測日期\*\*[:：]\s*(.+)$")


def render_cover_page(pdf, tool_value: str, date_value: str) -> None:
    pdf.add_page()
    pdf.image(COVER_TEMPLATE_PATH, x=0, y=0, w=210, h=297)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Body", "B", 15.5)
    pdf.set_xy(*COVER_TOOL_XY_MM)
    pdf.cell(120, COVER_VALUE_ROW_H_MM, tool_value, align="L")
    pdf.set_xy(*COVER_DATE_XY_MM)
    pdf.cell(150, COVER_VALUE_ROW_H_MM, date_value, align="L")
    pdf.set_text_color(*COLOR_DEFAULT)


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
    if severity == "Low":
        return COLOR_LOW
    return COLOR_DEFAULT


def build_pdf(md_path: str, pdf_path: str, font_path: str, bold_font_path: str = None) -> None:
    md_dir = os.path.dirname(os.path.abspath(md_path))
    with open(md_path, encoding="utf-8") as f:
        raw_lines = f.read().splitlines()
    # CJK fonts typically have no glyph for \t, and fpdf2 warns per character.
    lines = [EMOJI_PATTERN.sub("", line).replace("\t", " ").rstrip() for line in raw_lines]

    pdf = FPDF()
    # We never author intentional __underline__ spans in report content, and
    # source text legitimately contains literal "--" (CLI flags like
    # `--rpc-url` quoted in a finding's 說明). fpdf2 treats "--" as its
    # underline marker; an unpaired one silently underlines everything from
    # there to the end of the cell. Disable the marker rather than trying to
    # escape every "--" occurrence in upstream content.
    pdf.MARKDOWN_UNDERLINE_MARKER = "\0\0"
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("Body", "", font_path)
    pdf.add_font("Body", "B", bold_font_path or font_path)

    # The cover page's title/tool/date come straight out of the report's own
    # first lines (single source of truth) rather than being passed in
    # separately. If found and the bundled asset is present, render a cover
    # and drop those exact lines from the normal body flow so they don't
    # also print again as the first thing on page 2.
    skip_line_indices = set()
    if os.path.isfile(COVER_TEMPLATE_PATH):
        title_idx = tool_idx = date_idx = None
        tool_value = date_value = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if title_idx is None and COVER_TITLE_RE.match(stripped):
                title_idx = i
            m_tool = COVER_TOOL_RE.match(stripped)
            m_date = COVER_DATE_RE.match(stripped)
            if m_tool and tool_value is None:
                tool_value, tool_idx = m_tool.group(1), i
            if m_date and date_value is None:
                date_value, date_idx = m_date.group(1), i
            if None not in (title_idx, tool_value, date_value):
                break
        if None not in (title_idx, tool_value, date_value):
            render_cover_page(pdf, tool_value, date_value)
            skip_line_indices = {title_idx, tool_idx, date_idx}
            # Also absorb the blank lines and the "---" divider right after
            # the metadata block (report.md always has one there, closing
            # off the title/tool/date header) so page 2 doesn't open on a
            # stray empty gap + orphaned horizontal rule.
            j = max(skip_line_indices) + 1
            while j < len(lines) and lines[j].strip() == "":
                skip_line_indices.add(j)
                j += 1
            if j < len(lines) and lines[j].strip() == "---":
                skip_line_indices.add(j)
    pdf.add_page()
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

    def banner_box(text):
        """A colored, rounded-corner box for standalone '**【...】**' lines
        (currently only render_internal_banner()'s work-in-progress notice) —
        the warning-badge treatment from the design spec's status-badge
        pattern, applied to a full-width paragraph instead of an inline tag."""
        pdf.set_font("Body", "B", 12)
        pad = 4
        page_width = pdf.w - pdf.l_margin - pdf.r_margin
        text_width = page_width - 2 * pad
        wrapped = pdf.multi_cell(text_width, 6, text, border=0, align="L", dry_run=True, output="LINES") or [""]
        box_height = len(wrapped) * 6 + 2 * pad
        if pdf.get_y() + box_height > pdf.page_break_trigger:
            pdf.add_page()
        y0 = pdf.get_y()
        pdf.set_fill_color(*COLOR_BANNER_BG)
        pdf.set_draw_color(*COLOR_BANNER_TEXT)
        pdf.set_line_width(0.4)
        pdf.rect(pdf.l_margin, y0, page_width, box_height, style="DF", round_corners=True, corner_radius=2.5)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.set_xy(pdf.l_margin + pad, y0 + pad)
        pdf.set_text_color(*COLOR_BANNER_TEXT)
        pdf.multi_cell(text_width, 6, text, border=0, align="L", markdown=True)
        pdf.set_text_color(*COLOR_DEFAULT)
        pdf.set_xy(pdf.l_margin, y0 + box_height)
        pdf.ln(4)

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
        table_top_page = pdf.page_no()
        table_top_y = pdf.get_y()
        for i, row in enumerate(parsed):
            is_header = i == 0
            is_bold_row = is_header or any("**" in c for c in raw_cells[i])
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
                table_top_page = pdf.page_no()
                table_top_y = pdf.get_y()
            y0 = pdf.get_y()
            # 底色：表頭 Gray 100，資料列偶數斑馬紋 Gray 50，其餘白底
            # （BSOS 文件規格設計系統 §3 表格繪製規範 — 淺色主題）。
            if is_header:
                fill = GRAY_100
            elif (i - 1) % 2 == 1:
                fill = GRAY_50
            else:
                fill = None
            if fill:
                pdf.set_fill_color(*fill)
                pdf.rect(x0, y0, col_width * ncols, row_height, style="F")
            pdf.set_text_color(*(GRAY_900 if is_header else GRAY_800))
            for ci, cell in enumerate(row):
                x = x0 + ci * col_width
                pdf.set_xy(x, y0)
                pdf.multi_cell(col_width, line_height, cell, border=0, align="L")
            pdf.set_text_color(*COLOR_DEFAULT)
            # 直向欄位分隔線
            pdf.set_draw_color(*GRAY_300)
            pdf.set_line_width(0.15)
            for ci in range(1, ncols):
                x = x0 + ci * col_width
                pdf.line(x, y0, x, y0 + row_height)
            # 橫向列分隔線：表頭下緣加粗 Gray 400，其餘 Gray 200 細線
            pdf.set_draw_color(*(GRAY_400 if is_header else GRAY_200))
            pdf.set_line_width(0.3 if is_header else 0.15)
            pdf.line(x0, y0 + row_height, x0 + col_width * ncols, y0 + row_height)
            pdf.set_draw_color(0, 0, 0)
            pdf.set_line_width(0.2)
            pdf.set_xy(x0, y0 + row_height)
        table_bottom_y = pdf.get_y()
        # 外框圓角僅在整張表未跨頁時繪製；跨頁的表格保留格線但不強行畫外框，
        # 避免圓角矩形橫跨分頁邊界時的視覺錯誤。
        if pdf.page_no() == table_top_page:
            pdf.set_draw_color(*GRAY_700)
            pdf.set_line_width(0.6)
            pdf.rect(
                x0, table_top_y, col_width * ncols, table_bottom_y - table_top_y,
                round_corners=True, corner_radius=2.5,
            )
            pdf.set_draw_color(0, 0, 0)
            pdf.set_line_width(0.2)
        pdf.ln(4)
        pdf.set_x(pdf.l_margin)

    # Tracks which A/B/C/D classification section (§7) or manual-findings
    # section (§6) we're currently inside, so finding-title bullets can be
    # colored gray when they're category C (false positive) even though
    # their raw Slither impact might be High. Reset on every "## " (new major
    # section) and updated on every "### " category sub-heading.
    current_category = None

    for line_idx, line in enumerate(lines):
        if line_idx in skip_line_indices:
            continue
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
            para(heading_text, size=13, style="B", gap=8, color=COLOR_HEADING)
        elif stripped.startswith("## "):
            current_category = None
            para(stripped[3:], size=15, style="B", gap=9, color=COLOR_HEADING)
            y = pdf.get_y()
            pdf.set_draw_color(*COLOR_HEADING)
            pdf.set_line_width(0.5)
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.set_draw_color(0, 0, 0)
            pdf.set_line_width(0.2)
            pdf.ln(3)
        elif stripped.startswith("# "):
            current_category = None
            para(stripped[2:], size=18, style="B", gap=10, color=COLOR_HEADING)
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
        elif BANNER_RE.match(stripped):
            banner_box(BANNER_RE.match(stripped).group(1))
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
