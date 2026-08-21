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
    # macOS: Noto Sans CJK is not bundled with the OS, so it lands in one of
    # the user/local font dirs when installed by hand or via Homebrew cask.
    # The TC (traditional) cut is listed first — this project's reports are
    # zh-Hant, and 設計系統 §2.8 names Noto Sans TC as the document face.
    os.path.expanduser("~/Library/Fonts/NotoSansCJKtc-Regular.otf"),
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
    os.path.expanduser("~/Library/Fonts/NotoSansCJK-Regular.ttc"),
    "/Library/Fonts/NotoSansCJK-Regular.ttc",
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
    "NotoSansCJKtc-Regular.otf": "NotoSansCJKtc-Bold.otf",
}

# Tables at or below this many rows are kept whole: they are metadata blocks,
# not data listings, and splitting one costs more than the whitespace saved.
KEEP_TOGETHER_ROWS = 6

# Longest inline-code span whose spaces are made non-breaking. Beyond this a
# span could exceed the text column, leaving fpdf2 no legal break point.
MAX_NOBREAK_SPAN = 40

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


# fpdf2's markdown=True treats a DOUBLE underscore as an italic delimiter and
# consumes it. Solidity reports are full of identifiers that start with one --
# OpenZeppelin's `__gap` storage slot and every `__Xxx_init` initializer -- so
# `__gap` silently rendered as `gap` in the PDF while the markdown source was
# correct. Corrupting an identifier in a security report is worse than losing
# italics, and there is no escape syntax in fpdf's markdown, so break the
# delimiter pair with a zero-width space: visually identical, no longer parsed
# as markup. Single underscores and single asterisks are left alone -- verified
# not to be delimiters. `**bold**` is deliberately preserved.
_ZWSP = "​"


def neutralize_markdown_delimiters(text: str) -> str:
    return text.replace("__", f"_{_ZWSP}_")


def strip_code_markup(text: str) -> str:
    """Drop inline-code backticks but keep **bold** markers intact — those are
    rendered by fpdf2's own markdown=True, not manually stripped.

    Spaces inside a code span become non-breaking first. Line breaking happens
    at spaces, and the only spaces in an otherwise CJK sentence are the ones
    inside the code — so `params.length != 0` was a preferred break point and
    wrapped after the `!=`, splitting one expression across two lines. The
    backticks are gone by the time the text reaches the renderer, so this is
    the last point at which the span's extent is still known."""
    def keep_together(m):
        span = m.group(1)
        # Only short spans. A non-breaking run wider than the text column has
        # no break point left and fpdf2 raises "Not enough horizontal space to
        # render a single character" rather than overflowing.
        if len(span) > MAX_NOBREAK_SPAN:
            return span
        return span.replace(" ", "\u00a0")

    return neutralize_markdown_delimiters(re.sub(r"`(.*?)`", keep_together, text))


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

# Running header/footer assets (BSOS 文件規格設計系統 v1.0 — brand logo lockup,
# §1.4/1.5 gradient accent built from the cover's own Sky 300/Lime 400/Violet
# 500 stops). Both are optional: missing either just degrades to no logo /
# no gradient bar rather than failing the build.
LOGO_HEADER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "bsos_logo_header.png")
GRADIENT_BAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "gradient_bar.png")
HEADER_META_GRAY = (138, 147, 161)  # slate gray sampled from the designer's report_BSOS.pdf mockup header/footer


class ReportPDF(FPDF):
    """Adds a running page header (logo + gradient rule + title/tool/date
    breadcrumb) and footer (rule + internal-version notice or page number) to
    every page except the cover, matching the designer's report_BSOS.pdf
    mockup. Attributes are set by build_pdf() right after construction, before
    any add_page() call, since header()/footer() fire automatically inside
    add_page()/close()."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cover_rendered = False
        self.report_title = ""
        self.report_tool = ""
        self.report_date = ""
        self.is_internal = False

    def _on_cover_page(self) -> bool:
        return self.cover_rendered and self.page_no() == 1

    def header(self):
        if self._on_cover_page():
            return
        margin_l, margin_r = self.l_margin, self.r_margin
        content_w = self.w - margin_l - margin_r

        logo_h = 5.5
        logo_y = 8
        if os.path.isfile(LOGO_HEADER_PATH):
            self.image(LOGO_HEADER_PATH, x=margin_l, y=logo_y, h=logo_h)

        bar_y = logo_y + logo_h + 2.2
        bar_h = 0.9
        if os.path.isfile(GRADIENT_BAR_PATH):
            self.image(GRADIENT_BAR_PATH, x=margin_l, y=bar_y, w=content_w, h=bar_h)

        row_y = bar_y + bar_h + 2.6
        self.set_xy(margin_l, row_y)
        self.set_font("Body", "B", 11)
        self.set_text_color(*COLOR_HEADING)
        self.cell(content_w * 0.6, 6, self.report_title, align="L")
        meta = [p for p in (
            f"檢測工具：{self.report_tool}" if self.report_tool else "",
            f"檢測日期：{self.report_date}" if self.report_date else "",
        ) if p]
        if meta:
            self.set_xy(margin_l, row_y)
            self.set_font("Body", "", 8.5)
            self.set_text_color(*HEADER_META_GRAY)
            self.cell(content_w, 6, "   |   ".join(meta), align="R")

        rule_y = row_y + 7.5
        self.set_draw_color(*GRAY_300)
        self.set_line_width(0.2)
        self.line(margin_l, rule_y, self.w - margin_r, rule_y)
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.2)
        self.set_text_color(*COLOR_DEFAULT)
        self.set_y(rule_y + 4)

    def footer(self):
        if self._on_cover_page():
            return
        margin_l, margin_r = self.l_margin, self.r_margin
        y = self.h - 15
        self.set_draw_color(*GRAY_300)
        self.set_line_width(0.2)
        self.line(margin_l, y, self.w - margin_r, y)
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.2)
        self.set_y(y + 2)
        self.set_font("Body", "", 8.5)
        self.set_text_color(*HEADER_META_GRAY)
        if self.is_internal:
            self.cell(0, 5, "內部工作版本 — 不可作為交付文件", align="L")
        else:
            self.set_x(margin_l)
            self.cell(self.w - margin_l - margin_r - 25, 5, self.report_title, align="L")
            self.set_x(self.w - margin_r - 25)
            self.cell(25, 5, f"第 {self.page_no()} / {{nb}} 頁", align="R")
        self.set_text_color(*COLOR_DEFAULT)


def render_cover_page(pdf, tool_value: str, date_value: str) -> None:
    pdf.add_page()
    pdf.image(COVER_TEMPLATE_PATH, x=0, y=0, w=210, h=297)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Body", "B", 15.5)
    # KNOWN ISSUE, not yet root-caused: with some CJK font files (confirmed
    # on a Noto Sans CJK TC .otf build) these two short ASCII cells
    # intermittently render as garbled glyphs ("Slither" -> "6B") on a full
    # ~30-page report, even though the PDF's underlying text layer stays
    # correct (copy/paste and pdf.get_text() both read back correctly —
    # only the drawn glyphs are wrong). Not reproducible on an isolated
    # single-page cover, and not reproducible at all so far with a PingFang
    # .ttc build, so this looks like an fpdf2/fonttools glyph-subsetting bug
    # tied to specific font file internals rather than anything in this
    # function. Tried routing this text through fpdf2's core Helvetica font
    # instead of "Body" to dodge it — made things worse (corrupted CJK
    # rendering on *every* other page, not just the cover). Until root-
    # caused: prefer a PingFang-family font for report generation if you hit
    # this, and visually spot-check the cover after generating.
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

    pdf = ReportPDF()
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
    # fpdf2's markdown parser can emit style "I"/"BI" for text we never meant
    # as italic, and an unregistered style raises rather than degrading -- one
    # stray delimiter in one finding aborted the whole PDF. CJK faces rarely
    # ship a true italic, so alias them to the upright faces: the report keeps
    # rendering instead of dying over emphasis nobody asked for.
    pdf.add_font("Body", "I", font_path)
    pdf.add_font("Body", "BI", bold_font_path or font_path)

    # The cover page's / running header's title/tool/date come straight out
    # of the report's own first lines (single source of truth) rather than
    # being passed in separately. Extracted unconditionally so the running
    # header (every page) has them even when the cover asset is missing;
    # the cover render itself, and dropping these exact lines from the
    # normal body flow, still only happens when the bundled asset exists.
    title_idx = tool_idx = date_idx = None
    title_value = tool_value = date_value = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if title_idx is None:
            m_title = COVER_TITLE_RE.match(stripped)
            if m_title:
                title_value, title_idx = m_title.group(1), i
        m_tool = COVER_TOOL_RE.match(stripped)
        m_date = COVER_DATE_RE.match(stripped)
        if m_tool and tool_value is None:
            tool_value, tool_idx = m_tool.group(1), i
        if m_date and date_value is None:
            # scan_date is an ISO timestamp with microseconds; the cover and
            # running header want a date, not "2026-08-12T22:47:07.263397".
            date_value, date_idx = m_date.group(1).split("T")[0].strip(), i
        if None not in (title_idx, tool_value, date_value):
            break
    pdf.report_title = title_value or ""
    pdf.report_tool = tool_value or ""
    pdf.report_date = date_value or ""
    pdf.is_internal = any(BANNER_RE.match(line.strip()) for line in lines)

    skip_line_indices = set()
    if os.path.isfile(COVER_TEMPLATE_PATH) and None not in (title_idx, tool_value, date_value):
        render_cover_page(pdf, tool_value, date_value)
        pdf.cover_rendered = True
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

    def draw_table_frame(x, y, w, h, rounded=True):
        if h <= 0:
            return
        pdf.set_draw_color(*GRAY_700)
        pdf.set_line_width(0.6)
        if rounded:
            pdf.rect(x, y, w, h, round_corners=True, corner_radius=2.5)
        else:
            pdf.rect(x, y, w, h)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)

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
        # A finding's metadata table is a handful of rows that belong together;
        # letting two of them slide onto the next page orphans the rest under a
        # header they no longer sit beneath. Break before the table instead.
        if len(parsed) <= KEEP_TOGETHER_ROWS:
            needed = len(parsed) * line_height + 4
            if pdf.get_y() + needed > pdf.page_break_trigger:
                pdf.add_page()
        table_top_page = pdf.page_no()
        table_top_y = pdf.get_y()
        split = False
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
                # Close the outer frame around the part that stays on this page
                # before leaving it — otherwise only the final segment gets a
                # frame and every earlier page shows bare gridlines.
                draw_table_frame(x0, table_top_y, col_width * ncols, pdf.get_y() - table_top_y, rounded=not split)
                split = True
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
        # 每個分頁片段各自收框：未跨頁時圓角，跨頁片段用直角，
        # 讓斷開處看起來是被切斷而不是一個畫歪的圓角矩形。
        draw_table_frame(x0, table_top_y, col_width * ncols, pdf.get_y() - table_top_y, rounded=not split)
        pdf.ln(4)
        pdf.set_x(pdf.l_margin)

    # Tracks which A/B/C/D classification section (§7) or manual-findings
    # section (§6) we're currently inside, so finding-title bullets can be
    # colored gray when they're category C (false positive) even though
    # their raw Slither impact might be High. Reset on every "## " (new major
    # section) and updated on every "### " category sub-heading.
    current_category = None
    seen_section = False

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
            # Each top-level section starts on its own page (the layout the
            # third-party audit reports this document is compared against use).
            # The FIRST section is exempt: it follows the title block and the
            # internal-draft banner, and breaking there leaves a near-empty
            # sheet carrying nothing but the banner.
            if seen_section:
                pdf.add_page()
            seen_section = True
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
        elif stripped.startswith("<sub>"):
            # The scope section prints per-file SHA-256 values as fine print:
            # needed for the client to verify they received the scanned code,
            # but not something that should compete with the body text.
            clean = re.sub(r"</?(sub|br)\s*/?>", "", stripped).strip()
            if clean:
                para(clean, size=7, color=(120, 120, 120))
            else:
                pdf.ln(2)
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
