"""
Convert USER_GUIDE.md to a styled PDF reusing md_to_pdf's Doc class.
Run: python scripts/generate_user_guide.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the scripts directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from md_to_pdf import (
    Doc,
    GRAY,
    NAVY,
    TEAL,
    LGRAY,
    WHITE,
    BLACK,
    parse_and_render,
    _clean,
)
from fpdf.enums import XPos, YPos

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "USER_GUIDE.md"
PDF_PATH = ROOT / "USER_GUIDE.pdf"


# ---------------------------------------------------------------------------
# Subclass with custom cover + header
# ---------------------------------------------------------------------------
class UserGuideDoc(Doc):
    """Doc variant with User Guide branding."""

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Arial", "B", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 8, "Horizon Capital -- User Guide", align="L",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*LGRAY)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def cover(self):
        self.add_page()
        # Navy accent bar
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 60, "F")

        # Title
        self.set_y(18)
        self.set_font("Arial", "B", 28)
        self.set_text_color(*WHITE)
        self.cell(0, 12, "Horizon Capital", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Arial", "", 14)
        self.cell(0, 8, "User Guide", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Arial", "", 9)
        self.set_text_color(*LGRAY)
        self.cell(0, 6, "Version 0.2.0  |  2026-03-25", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Table of contents
        self.set_y(75)
        self.set_text_color(*BLACK)

        sections = [
            ("1", "User Personas"),
            ("2", "Getting Started"),
            ("3", "Platform Modes"),
            ("4", "Step-by-Step Workflows"),
            ("5", "Command Reference"),
            ("6", "Configuration Guide"),
            ("7", "Troubleshooting"),
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not MD_PATH.exists():
        print(f"ERROR: {MD_PATH} not found", file=sys.stderr)
        sys.exit(1)

    md_text = MD_PATH.read_text(encoding="utf-8")

    doc = UserGuideDoc()
    doc.cover()
    doc.add_page()
    parse_and_render(doc, md_text)

    doc.output(str(PDF_PATH))
    print(f"PDF written to: {PDF_PATH}")
    print(f"Pages: {doc.page_no()}")


if __name__ == "__main__":
    main()
