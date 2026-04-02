"""
Convert IMPLEMENTATION_AND_TESTS.md to a styled PDF.
Run: python scripts/impl_tests_to_pdf.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT     = Path(__file__).resolve().parent.parent
MD_PATH  = ROOT / "IMPLEMENTATION_AND_TESTS.md"
PDF_PATH = ROOT / "IMPLEMENTATION_AND_TESTS.pdf"

# Colours
NAVY          = (15,  40,  80)
TEAL          = (0,   120, 130)
GREEN         = (0,   130, 70)
ORANGE        = (200, 100, 0)
GRAY          = (80,  80,  80)
LGRAY         = (220, 220, 220)
WHITE         = (255, 255, 255)
BLACK         = (20,  20,  20)
CODE_BG       = (245, 245, 250)
CODE_FG       = (30,  30,  100)
TBL_HDR       = (15,  40,  80)
TBL_ALT       = (240, 245, 255)
DONE_BG       = (230, 255, 235)
PENDING_BG    = (255, 245, 220)

FONT_DIR     = Path("C:/Windows/Fonts")
FONT_REG     = str(FONT_DIR / "arial.ttf")
FONT_BOLD    = str(FONT_DIR / "arialbd.ttf")
FONT_ITALIC  = str(FONT_DIR / "ariali.ttf")
FONT_BI      = str(FONT_DIR / "arialbi.ttf")
FONT_MONO    = str(FONT_DIR / "cour.ttf")
FONT_MONO_B  = str(FONT_DIR / "courbd.ttf")


def _clean(text: str) -> str:
    table = {
        "\u2014": "--", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"',  "\u201d": '"', "\u2022": "-", "\u25e6": "-",
        "\u2192": "->", "\u2713": "[DONE]", "\u2705": "[DONE]",
        "\u274c": "[X]", "\u2026": "...", "\u00b2": "^2",
        "\u221a": "sqrt", "\u03b1": "alpha", "\u03b2": "beta",
        "\u03c3": "sigma", "\u03b5": "eps", "\u03c9": "omega",
        "\u03ba": "kappa", "\u03b8": "theta", "\u03bc": "mu",
        "\u2264": "<=", "\u2265": ">=", "\u00b1": "+/-",
    }
    for src, dst in table.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


class Doc(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(18, 18, 18)
        self.add_font("Arial", style="",   fname=FONT_REG)
        self.add_font("Arial", style="B",  fname=FONT_BOLD)
        self.add_font("Arial", style="I",  fname=FONT_ITALIC)
        self.add_font("Arial", style="BI", fname=FONT_BI)
        self.add_font("Mono",  style="",   fname=FONT_MONO)
        self.add_font("Mono",  style="B",  fname=FONT_MONO_B)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Arial", "B", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 7, "Horizon Capital -- Implementation Guide & Test Cases",
                  align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*LGRAY)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def footer(self):
        self.set_y(-14)
        self.set_font("Arial", "", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")

    def _uw(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def _rule(self, color=LGRAY, lw=0.3):
        self.set_draw_color(*color)
        self.set_line_width(lw)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    # ------------------------------------------------------------------ Cover
    def cover(self):
        self.add_page()
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 55, "F")

        self.set_y(15)
        self.set_font("Arial", "B", 26)
        self.set_text_color(*WHITE)
        self.cell(0, 11, "Horizon Capital", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Arial", "", 13)
        self.cell(0, 8, "Implementation Guide & Test Cases", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Arial", "", 9)
        self.set_text_color(*LGRAY)
        self.cell(0, 5, "v0.2.0  |  2026-03-24  |  300+ tests passing", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_y(68)
        self.set_text_color(*BLACK)

        parts = [
            ("Part 1", "Implementation Steps", "Phases 1-9 with commands to verify each"),
            ("Part 2", "Test Cases T-01 to T-20", "20 test groups, 300+ individual assertions"),
            ("Part 3", "Quick Reference", "Run commands, lint, coverage gaps"),
        ]
        for num, title, desc in parts:
            self.set_font("Arial", "B", 10)
            self.set_text_color(*NAVY)
            self.cell(20, 7, num)
            self.set_font("Arial", "B", 10)
            self.set_text_color(*BLACK)
            self.cell(55, 7, title)
            self.set_font("Arial", "", 9)
            self.set_text_color(*GRAY)
            self.cell(0, 7, desc, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self._rule(LGRAY, 0.2)

        # Stats box
        self.ln(5)
        self.set_fill_color(*TBL_ALT)
        box_y = self.get_y()
        self.rect(self.l_margin, box_y, self._uw(), 28, "F")
        self.set_xy(self.l_margin + 4, box_y + 4)

        stats = [
            ("9", "Phases"),
            ("300+", "Tests"),
            ("40+", "REPL Commands"),
            ("23", "DB Tables"),
            ("26+", "Backtest Metrics"),
            ("4", "ML Models"),
        ]
        cell_w = self._uw() / len(stats)
        for val, label in stats:
            x = self.get_x()
            self.set_font("Arial", "B", 14)
            self.set_text_color(*NAVY)
            self.cell(cell_w, 8, val, align="C")
        self.ln(9)
        self.set_x(self.l_margin + 4)
        for val, label in stats:
            self.set_font("Arial", "", 7)
            self.set_text_color(*GRAY)
            self.cell(cell_w, 5, label, align="C")
        self.ln(10)
        self.set_text_color(*BLACK)

    # --------------------------------------------------------------- Headings
    def h1(self, text: str):
        self.ln(4)
        self.set_fill_color(*NAVY)
        self.set_text_color(*WHITE)
        self.set_font("Arial", "B", 12)
        self.cell(0, 8, _clean(f"  {text}"), fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def h2(self, text: str):
        self.ln(3)
        # Color-code by status keyword
        if "[DONE]" in text or "DONE" in text:
            self.set_text_color(*GREEN)
        elif "PENDING" in text or "TODO" in text:
            self.set_text_color(*ORANGE)
        elif text.startswith("T-") or "Test" in text:
            self.set_text_color(*TEAL)
        else:
            self.set_text_color(*TEAL)
        self.set_font("Arial", "B", 11)
        self.cell(0, 7, _clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self._rule(TEAL, 0.4)
        self.set_text_color(*BLACK)

    def h3(self, text: str):
        self.ln(2)
        self.set_text_color(*NAVY)
        self.set_font("Arial", "B", 10)
        self.cell(0, 6, _clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*BLACK)

    def h4(self, text: str):
        self.ln(1)
        self.set_text_color(*GRAY)
        self.set_font("Arial", "BI", 9)
        self.cell(0, 5, _clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*BLACK)

    # ------------------------------------------------------------------- Body
    def para(self, text: str):
        if not text.strip():
            return
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        self.set_font("Arial", "", 9)
        self.set_text_color(*BLACK)
        self.multi_cell(0, 5, _clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def bullet(self, text: str, level: int = 0):
        indent = 4 + level * 4
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        self.set_font("Arial", "", 9)
        self.set_text_color(*BLACK)
        self.set_x(self.l_margin + indent)
        self.cell(4, 5, "-")
        self.multi_cell(self._uw() - indent - 4, 5, _clean(text),
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ------------------------------------------------------------------- Code
    def code_block(self, lines: list[str]):
        self.ln(1)
        text = _clean("\n".join(lines))
        n_lines = text.count("\n") + 1
        h = n_lines * 4.2 + 5
        if self.get_y() + h > self.h - self.b_margin:
            self.add_page()
        self.set_fill_color(*CODE_BG)
        self.set_draw_color(*LGRAY)
        self.set_line_width(0.2)
        self.rect(self.l_margin, self.get_y(), self._uw(), h, "DF")
        self.set_xy(self.l_margin + 2, self.get_y() + 2)
        self.set_font("Mono", "", 7.5)
        self.set_text_color(*CODE_FG)
        self.multi_cell(self._uw() - 4, 4.2, text,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*BLACK)
        self.ln(2)

    # ------------------------------------------------------------------ Table
    def md_table(self, rows: list[list[str]]):
        if len(rows) < 2:
            return
        headers  = rows[0]
        data     = rows[2:] if len(rows) > 2 else []
        n        = len(headers)
        if n == 0:
            return

        col_lens = [max(len(h), 3) for h in headers]
        for row in data:
            for i, c in enumerate(row):
                if i < n:
                    col_lens[i] = max(col_lens[i], min(len(c), 45))
        total = sum(col_lens) or 1
        col_w = [self._uw() * (l / total) for l in col_lens]
        rh = 5.5

        if self.get_y() + rh * 2 > self.h - self.b_margin:
            self.add_page()

        # Header
        self.set_font("Arial", "B", 7.5)
        self.set_fill_color(*TBL_HDR)
        self.set_text_color(*WHITE)
        x0, y0 = self.l_margin, self.get_y()
        for hdr, w in zip(headers, col_w):
            self.set_xy(x0, y0)
            self.cell(w, rh, _clean(f" {hdr}"), fill=True)
            x0 += w
        self.ln(rh)

        # Rows
        self.set_font("Arial", "", 7.5)
        for ri, row in enumerate(data):
            if self.get_y() + rh > self.h - self.b_margin:
                self.add_page()
            fill = ri % 2 == 1
            # Highlight DONE / PENDING rows
            row_text = " ".join(row)
            if "DONE" in row_text or "[DONE]" in row_text:
                self.set_fill_color(*DONE_BG)
                fill = True
            elif "PENDING" in row_text or "TODO" in row_text:
                self.set_fill_color(*PENDING_BG)
                fill = True
            else:
                self.set_fill_color(*TBL_ALT)

            self.set_text_color(*BLACK)
            x0, y0 = self.l_margin, self.get_y()
            for cell, w in zip(row, col_w):
                ct = cell.strip().lstrip("|").rstrip("|").strip()
                ct = re.sub(r"`([^`]+)`", r"\1", ct)
                ct = re.sub(r"\*\*([^*]+)\*\*", r"\1", ct)
                self.set_xy(x0, y0)
                self.cell(w, rh, _clean(f" {ct[:60]}"), border="B", fill=fill)
                x0 += w
            self.set_draw_color(*LGRAY)
            self.ln(rh)
        self.ln(3)


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

        if "|" in line and line.strip().startswith("|"):
            if not in_table:
                flush_table()
                in_table = True
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            table_rows.append(cols)
            i += 1
            continue
        elif in_table:
            flush_table()

        if line.startswith("#### "):
            doc.h4(line[5:].strip())
        elif line.startswith("### "):
            doc.h3(line[4:].strip())
        elif line.startswith("## "):
            doc.h2(line[3:].strip())
        elif line.startswith("# "):
            doc.h1(line[2:].strip())
        elif line.startswith("---"):
            doc._rule(LGRAY, 0.3)
        elif re.match(r"^\d+\. ", line):
            doc.bullet(re.sub(r"^\d+\. ", "", line).strip(), level=0)
        elif re.match(r"^[-*] ", line):
            doc.bullet(line[2:].strip(), level=0)
        elif re.match(r"^ {2,4}[-*] ", line):
            doc.bullet(re.sub(r"^ {2,4}[-*] ", "", line).strip(), level=1)
        elif line.strip() == "":
            doc.ln(1)
        else:
            doc.para(line.strip())

        i += 1

    if in_table:
        flush_table()


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
