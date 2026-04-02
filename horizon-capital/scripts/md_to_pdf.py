"""
Convert TECHNICAL_DEEP_DIVE.md to a styled PDF using fpdf2.
Run: python scripts/md_to_pdf.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "TECHNICAL_DEEP_DIVE.md"
PDF_PATH = ROOT / "TECHNICAL_DEEP_DIVE.pdf"


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
NAVY   = (15,  40,  80)
TEAL   = (0,   120, 130)
GRAY   = (80,  80,  80)
LGRAY  = (220, 220, 220)
WHITE  = (255, 255, 255)
BLACK  = (20,  20,  20)
CODE_BG = (245, 245, 250)
CODE_FG = (40,  40,  100)
TABLE_HEADER_BG = (15, 40, 80)
TABLE_ROW_ALT   = (240, 245, 255)

# Windows font paths
FONT_DIR = Path("C:/Windows/Fonts")
FONT_REGULAR = str(FONT_DIR / "arial.ttf")
FONT_BOLD    = str(FONT_DIR / "arialbd.ttf")
FONT_ITALIC  = str(FONT_DIR / "ariali.ttf")
FONT_BI      = str(FONT_DIR / "arialbi.ttf")
FONT_MONO    = str(FONT_DIR / "cour.ttf")      # Courier New (mono)
FONT_MONO_B  = str(FONT_DIR / "courbd.ttf")


def _clean(text: str) -> str:
    """Replace non-latin1 characters with ASCII equivalents."""
    replacements = {
        "\u2014": "--",   # em dash
        "\u2013": "-",    # en dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2022": "-",    # bullet
        "\u25e6": "-",    # white bullet
        "\u2192": "->",   # arrow right
        "\u25b6": ">",    # play button
        "\u2713": "OK",   # check mark
        "\u2714": "OK",
        "\u2705": "[x]",  # green check
        "\u274c": "[ ]",  # red x
        "\u2b50": "*",    # star
        "\u2026": "...",  # ellipsis
        "\u00b2": "^2",   # superscript 2
        "\u00b3": "^3",
        "\u221a": "sqrt", # square root
        "\u03b1": "alpha",
        "\u03b2": "beta",
        "\u03ba": "kappa",
        "\u03b8": "theta",
        "\u03c3": "sigma",
        "\u03b5": "epsilon",
        "\u03bc": "mu",
        "\u03c9": "omega",
        "\u03b3": "gamma",
        "\u03be": "xi",
        "\u0394": "Delta",
        "\u03c1": "rho",
        "\u2264": "<=",
        "\u2265": ">=",
        "\u00d7": "x",    # multiplication sign
        "\u00b0": "deg",
        "\u00b1": "+/-",
        "\u2248": "~=",
        "\u03a3": "Sigma",
        "\u03a9": "Omega",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    # Strip any remaining non-latin1 chars
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ---------------------------------------------------------------------------
# PDF class
# ---------------------------------------------------------------------------
class Doc(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(18, 18, 18)
        self._toc: list[tuple[int, str, int]] = []   # (level, title, page)
        # Register Unicode-capable Arial font family
        self.add_font("Arial", style="",   fname=FONT_REGULAR)
        self.add_font("Arial", style="B",  fname=FONT_BOLD)
        self.add_font("Arial", style="I",  fname=FONT_ITALIC)
        self.add_font("Arial", style="BI", fname=FONT_BI)
        self.add_font("Mono",  style="",   fname=FONT_MONO)
        self.add_font("Mono",  style="B",  fname=FONT_MONO_B)

    # ------------------------------------------------------------------
    # Header / footer
    # ------------------------------------------------------------------
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Arial", "B", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 8, "Horizon Capital -- Technical Deep Dive", align="L",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*LGRAY)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def footer(self):
        self.set_y(-14)
        self.set_font("Arial", "", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _usable_w(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def _rule(self, color=LGRAY, lw=0.3):
        self.set_draw_color(*color)
        self.set_line_width(lw)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------
    def cover(self):
        self.add_page()
        # Background accent bar
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 60, "F")

        # Title
        self.set_y(18)
        self.set_font("Arial", "B", 28)
        self.set_text_color(*WHITE)
        self.cell(0, 12, "Horizon Capital", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Arial", "", 14)
        self.cell(0, 8, "Technical Deep Dive", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Arial", "", 9)
        self.set_text_color(*LGRAY)
        self.cell(0, 6, "Version 0.2.0  |  2026-03-24", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_y(75)
        self.set_text_color(*BLACK)

        sections = [
            ("1", "Data Sources & API Contracts"),
            ("2", "Data Processing Pipeline"),
            ("3", "Feature Engineering"),
            ("4", "ML & AI Models -- Choices, Alternatives & Reasoning"),
            ("5", "Trading Strategies"),
            ("6", "Risk & Portfolio Management"),
            ("7", "Project Timeline (Detailed)"),
            ("8", "Dependency & Architecture Decisions"),
            ("*", "Research Papers Master List"),
        ]
        self.set_font("Arial", "B", 11)
        self.set_text_color(*NAVY)
        self.cell(0, 8, "Contents", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self._rule(TEAL, 0.6)
        self.ln(2)

        for num, title in sections:
            self.set_font("Arial", "", 10)
            self.set_text_color(*GRAY)
            self.cell(8, 7, num, align="R")
            self.set_x(self.l_margin + 12)
            self.set_text_color(*BLACK)
            self.cell(0, 7, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ------------------------------------------------------------------
    # Section heading (H1 = ##, H2 = ###, H3 = ####)
    # ------------------------------------------------------------------
    def h1(self, text: str):
        self.ln(4)
        self.set_fill_color(*NAVY)
        self.set_text_color(*WHITE)
        self.set_font("Arial", "B", 13)
        self.cell(0, 9, _clean(f"  {text}"), fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)
        self._toc.append((1, text, self.page_no()))

    def h2(self, text: str):
        self.ln(3)
        self.set_text_color(*TEAL)
        self.set_font("Arial", "B", 11)
        self.cell(0, 7, _clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self._rule(TEAL, 0.4)
        self.set_text_color(*BLACK)
        self._toc.append((2, text, self.page_no()))

    def h3(self, text: str):
        self.ln(2)
        self.set_text_color(*NAVY)
        self.set_font("Arial", "B", 10)
        self.cell(0, 6, _clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*BLACK)
        self._toc.append((3, text, self.page_no()))

    def h4(self, text: str):
        self.ln(1)
        self.set_text_color(*GRAY)
        self.set_font("Arial", "BI", 9)
        self.cell(0, 5, _clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*BLACK)

    # ------------------------------------------------------------------
    # Body paragraph
    # ------------------------------------------------------------------
    def para(self, text: str):
        if not text.strip():
            return
        self.set_font("Arial", "", 9)
        self.set_text_color(*BLACK)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        self.multi_cell(0, 5, _clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    # ------------------------------------------------------------------
    # Bullet
    # ------------------------------------------------------------------
    def bullet(self, text: str, level: int = 0):
        indent = 4 + level * 4
        bullet_char = "-"
        self.set_font("Arial", "", 9)
        self.set_text_color(*BLACK)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        self.set_x(self.l_margin + indent)
        self.cell(5, 5, bullet_char)
        self.multi_cell(self._usable_w() - indent - 5, 5, _clean(text),
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ------------------------------------------------------------------
    # Code block
    # ------------------------------------------------------------------
    def code_block(self, lines: list[str]):
        self.ln(1)
        text = _clean("\n".join(lines))
        self.set_fill_color(*CODE_BG)
        self.set_text_color(*CODE_FG)
        self.set_font("Mono", "", 7.5)
        self.set_draw_color(*LGRAY)
        self.set_line_width(0.2)
        lines_needed = text.count("\n") + 1
        h = lines_needed * 4 + 4
        # Page break if needed
        if self.get_y() + h > self.h - self.b_margin:
            self.add_page()
        self.rect(self.l_margin, self.get_y(), self._usable_w(), h, "DF")
        self.set_xy(self.l_margin + 2, self.get_y() + 2)
        self.multi_cell(self._usable_w() - 4, 4, text,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*BLACK)
        self.ln(2)

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------
    def _calc_cell_height(self, text: str, col_w: float, font_size: float = 7.5) -> float:
        """Calculate the height needed for wrapped text in a cell."""
        line_h = 4.0
        # Estimate chars per line (font_size 7.5 ≈ 2.1mm per char for Arial)
        char_w = font_size * 0.28  # approximate mm per character
        usable_cell_w = col_w - 2  # 1mm padding each side
        if usable_cell_w <= 0:
            usable_cell_w = col_w
        chars_per_line = max(int(usable_cell_w / char_w), 1)
        n_lines = 1
        for part in text.split("\n"):
            n_lines += max(0, (len(part) - 1) // chars_per_line)
            if part:
                n_lines_for_part = max(1, -(-len(part) // chars_per_line))  # ceil div
                n_lines += n_lines_for_part - 1  # first line already counted
        # Recalculate properly
        n_lines = 0
        for part in text.split("\n"):
            if not part:
                n_lines += 1
            else:
                n_lines += max(1, -(-len(part) // chars_per_line))
        return max(line_h, n_lines * line_h) + 1  # +1mm padding

    def _draw_table_row(self, cells: list[str], col_w: list[float],
                        row_h: float, fill: bool, is_header: bool = False):
        """Draw a single table row with text wrapping and uniform row height."""
        x0 = self.l_margin
        y0 = self.get_y()

        for cell_text, w in zip(cells, col_w):
            self.set_xy(x0, y0)
            if is_header:
                self.set_fill_color(*TABLE_HEADER_BG)
                self.rect(x0, y0, w, row_h, "F")
                self.set_xy(x0 + 1, y0 + 0.5)
                self.multi_cell(w - 2, 4.0, _clean(cell_text),
                                new_x=XPos.RIGHT, new_y=YPos.TOP)
            else:
                if fill:
                    self.set_fill_color(*TABLE_ROW_ALT)
                    self.rect(x0, y0, w, row_h, "F")
                # Bottom border
                self.set_draw_color(*LGRAY)
                self.line(x0, y0 + row_h, x0 + w, y0 + row_h)
                self.set_xy(x0 + 1, y0 + 0.5)
                self.multi_cell(w - 2, 4.0, _clean(cell_text),
                                new_x=XPos.RIGHT, new_y=YPos.TOP)
            x0 += w

        self.set_xy(self.l_margin, y0 + row_h)

    def md_table(self, rows: list[list[str]]):
        """rows[0] = headers, rows[1] = separator (ignored), rows[2+] = data"""
        if len(rows) < 2:
            return
        headers = rows[0]
        data_rows = rows[2:] if len(rows) > 2 else []

        n_cols = len(headers)
        if n_cols == 0:
            return

        usable = self._usable_w()

        # Clean all cell text first
        def _clean_cell(t: str) -> str:
            t = t.strip().lstrip("|").rstrip("|").strip()
            t = re.sub(r"`([^`]+)`", r"\1", t)
            t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
            return t

        cleaned_headers = [_clean_cell(h) for h in headers]
        cleaned_data = []
        for row in data_rows:
            cleaned_data.append([_clean_cell(row[i]) if i < len(row) else ""
                                 for i in range(n_cols)])

        # Compute column widths proportionally based on content length
        col_lens = [max(len(h), 4) for h in cleaned_headers]
        for row in cleaned_data:
            for i, cell in enumerate(row):
                if i < n_cols:
                    col_lens[i] = max(col_lens[i], min(len(cell), 50))
        total = sum(col_lens) or 1
        col_w = [usable * (cl / total) for cl in col_lens]

        # Enforce minimum column width of 15mm so text can wrap
        min_col_w = 15.0
        for i in range(n_cols):
            if col_w[i] < min_col_w:
                col_w[i] = min_col_w
        # Re-normalize to fit usable width
        scale = usable / sum(col_w)
        col_w = [w * scale for w in col_w]

        # Calculate header row height
        header_h = 5.5
        for h, w in zip(cleaned_headers, col_w):
            header_h = max(header_h, self._calc_cell_height(h, w))

        # Page break check for header
        if self.get_y() + header_h + 5.5 > self.h - self.b_margin:
            self.add_page()

        # Header row
        self.set_font("Arial", "B", 7.5)
        self.set_text_color(*WHITE)
        self._draw_table_row(cleaned_headers, col_w, header_h, fill=True, is_header=True)

        # Data rows
        self.set_font("Arial", "", 7.5)
        for ri, row in enumerate(cleaned_data):
            # Calculate row height based on tallest cell
            row_h = 5.5
            for cell_text, w in zip(row, col_w):
                row_h = max(row_h, self._calc_cell_height(cell_text, w))

            # Page break check
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
                # Repeat header on new page
                self.set_font("Arial", "B", 7.5)
                self.set_text_color(*WHITE)
                self._draw_table_row(cleaned_headers, col_w, header_h,
                                     fill=True, is_header=True)
                self.set_font("Arial", "", 7.5)

            fill = ri % 2 == 1
            self.set_text_color(*BLACK)
            self._draw_table_row(row, col_w, row_h, fill=fill, is_header=False)

        self.ln(3)


# ---------------------------------------------------------------------------
# Markdown parser → Doc calls
# ---------------------------------------------------------------------------
def parse_and_render(doc: Doc, md_text: str):
    lines = md_text.splitlines()
    i = 0
    in_code = False
    code_lines: list[str] = []
    table_rows: list[list[str]] = []
    in_table = False

    def flush_table():
        nonlocal table_rows, in_table
        if table_rows:
            doc.md_table(table_rows)
        table_rows = []
        in_table = False

    while i < len(lines):
        line = lines[i]

        # ---- Code fence ----
        if line.strip().startswith("```"):
            if not in_code:
                in_code = True
                code_lines = []
            else:
                in_code = False
                doc.code_block(code_lines)
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # ---- Table ----
        if "|" in line and line.strip().startswith("|"):
            if in_table:
                cols = [c.strip() for c in line.strip().strip("|").split("|")]
                table_rows.append(cols)
            else:
                flush_table()
                in_table = True
                cols = [c.strip() for c in line.strip().strip("|").split("|")]
                table_rows.append(cols)
            i += 1
            continue
        else:
            if in_table:
                flush_table()

        # ---- Headings ----
        if line.startswith("#### "):
            doc.h4(line[5:].strip())
        elif line.startswith("### "):
            doc.h3(line[4:].strip())
        elif line.startswith("## "):
            doc.h2(line[3:].strip())
        elif line.startswith("# "):
            # Top-level title -- skip (already on cover)
            pass
        elif line.startswith("---"):
            doc._rule(LGRAY, 0.3)
        elif re.match(r"^\d+\. ", line):
            # Numbered list
            text = re.sub(r"^\d+\. ", "", line).strip()
            doc.bullet(text, level=0)
        elif re.match(r"^[-*] ", line):
            doc.bullet(line[2:].strip(), level=0)
        elif re.match(r"^ {2,4}[-*] ", line):
            text = re.sub(r"^ {2,4}[-*] ", "", line).strip()
            doc.bullet(text, level=1)
        elif line.strip() == "":
            doc.ln(1)
        else:
            # Normal paragraph
            doc.para(line.strip())

        i += 1

    if in_table:
        flush_table()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not MD_PATH.exists():
        print(f"ERROR: {MD_PATH} not found", file=sys.stderr)
        sys.exit(1)

    md_text = MD_PATH.read_text(encoding="utf-8")

    doc = Doc()
    doc.cover()
    doc.add_page()
    parse_and_render(doc, md_text)

    doc.output(str(PDF_PATH))
    print(f"PDF written to: {PDF_PATH}")
    print(f"Pages: {doc.page_no()}")


if __name__ == "__main__":
    main()
