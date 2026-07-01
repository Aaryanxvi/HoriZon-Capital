"""Render every thesis figure into ./output."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

PY_FIGS = [
    "fig_3_5_almgren_chriss.py",
    "fig_4_5_sleeve_pie.py",
    "fig_5_1_test_distribution.py",
    "fig_5_2_equity_curve.py",
    "fig_5_3_gap_distribution.py",
]

MERMAID_FIGS = [
    ("fig_3_1_architecture.mmd",   1600, 1000),
    ("fig_3_2_bus_topology.mmd",   1600, 1000),
    ("fig_3_3_dept_hierarchy.mmd", 1600, 1100),
    ("fig_3_4_order_state.mmd",    1400,  900),
    ("fig_3_6_nav_flow.mmd",       1400,  900),
    ("fig_4_1_data_flow.mmd",      1700,  800),
    ("fig_4_2_sequence.mmd",       1400, 1100),
    ("fig_4_3_risk_tree.mmd",      1400, 1000),
    ("fig_4_4_monitor_loop.mmd",   1200, 1000),
]


def run_python_figs() -> None:
    py_dir = ROOT / "py"
    for fname in PY_FIGS:
        path = py_dir / fname
        print(f"[py ] {fname}")
        subprocess.check_call([sys.executable, str(path)], cwd=ROOT)


def run_mermaid_figs() -> None:
    mmd_dir = ROOT / "mermaid"
    mmdc = shutil.which("mmdc")
    if mmdc is None:
        print("[mmd] 'mmdc' not on PATH — skipping mermaid renders.")
        print("      Install via: npm install -g @mermaid-js/mermaid-cli")
        print("      Or paste .mmd files into https://mermaid.live")
        return
    for fname, w, h in MERMAID_FIGS:
        in_path = mmd_dir / fname
        out_path = OUT / fname.replace(".mmd", ".png")
        print(f"[mmd] {fname} -> {out_path.name}")
        subprocess.check_call([
            mmdc, "-i", str(in_path), "-o", str(out_path),
            "-w", str(w), "-H", str(h), "-b", "white",
        ])


if __name__ == "__main__":
    run_python_figs()
    run_mermaid_figs()
    print("\nDone. Outputs in:", OUT)
