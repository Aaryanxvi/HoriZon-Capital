# Thesis Figures — Generators

Run all generators from this directory. Outputs land in `output/`.

## Prerequisites

```bash
pip install matplotlib numpy
npm install -g @mermaid-js/mermaid-cli   # provides 'mmdc'
```

## Run all

```bash
python render_all.py
```

Or per-figure:

```bash
python py/fig_3_5_almgren_chriss.py
python py/fig_4_5_sleeve_pie.py
python py/fig_5_1_test_distribution.py
python py/fig_5_2_equity_curve.py
python py/fig_5_3_gap_distribution.py

mmdc -i mermaid/fig_3_1_architecture.mmd     -o output/fig_3_1_architecture.png     -w 1600 -H 1000
mmdc -i mermaid/fig_3_2_bus_topology.mmd     -o output/fig_3_2_bus_topology.png     -w 1600 -H 1000
mmdc -i mermaid/fig_3_3_dept_hierarchy.mmd   -o output/fig_3_3_dept_hierarchy.png   -w 1600 -H 1100
mmdc -i mermaid/fig_3_4_order_state.mmd      -o output/fig_3_4_order_state.png      -w 1400 -H  900
mmdc -i mermaid/fig_3_6_nav_flow.mmd         -o output/fig_3_6_nav_flow.png         -w 1400 -H  900
mmdc -i mermaid/fig_4_1_data_flow.mmd        -o output/fig_4_1_data_flow.png        -w 1700 -H  800
mmdc -i mermaid/fig_4_2_sequence.mmd         -o output/fig_4_2_sequence.png         -w 1400 -H 1100
mmdc -i mermaid/fig_4_3_risk_tree.mmd        -o output/fig_4_3_risk_tree.png        -w 1400 -H 1000
mmdc -i mermaid/fig_4_4_monitor_loop.mmd     -o output/fig_4_4_monitor_loop.png     -w 1200 -H 1000
```

## Figure inventory

| ID | File | Type | Source |
|----|------|------|--------|
| 3.1 | fig_3_1_architecture | Mermaid graph | `mermaid/fig_3_1_architecture.mmd` |
| 3.2 | fig_3_2_bus_topology | Mermaid graph | `mermaid/fig_3_2_bus_topology.mmd` |
| 3.3 | fig_3_3_dept_hierarchy | Mermaid graph | `mermaid/fig_3_3_dept_hierarchy.mmd` |
| 3.4 | fig_3_4_order_state | Mermaid stateDiagram | `mermaid/fig_3_4_order_state.mmd` |
| 3.5 | fig_3_5_almgren_chriss | Matplotlib | `py/fig_3_5_almgren_chriss.py` |
| 3.6 | fig_3_6_nav_flow | Mermaid flowchart | `mermaid/fig_3_6_nav_flow.mmd` |
| 4.1 | fig_4_1_data_flow | Mermaid flowchart | `mermaid/fig_4_1_data_flow.mmd` |
| 4.2 | fig_4_2_sequence | Mermaid sequence | `mermaid/fig_4_2_sequence.mmd` |
| 4.3 | fig_4_3_risk_tree | Mermaid flowchart | `mermaid/fig_4_3_risk_tree.mmd` |
| 4.4 | fig_4_4_monitor_loop | Mermaid flowchart | `mermaid/fig_4_4_monitor_loop.mmd` |
| 4.5 | fig_4_5_sleeve_pie | Matplotlib pie | `py/fig_4_5_sleeve_pie.py` |
| 4.6 | fig_4_6_dashboard | screenshot | capture from running TUI |
| 5.1 | fig_5_1_test_distribution | Matplotlib bar | `py/fig_5_1_test_distribution.py` |
| 5.2 | fig_5_2_equity_curve | Matplotlib line | `py/fig_5_2_equity_curve.py` |
| 5.3 | fig_5_3_gap_distribution | Matplotlib stacked bar | `py/fig_5_3_gap_distribution.py` |

For Fig 4.6, run `python -m app --mode PAPER_TRADING` from `backend/`, wait for dashboard, screenshot via Win+Shift+S, save as `output/fig_4_6_dashboard.png`.

## No-Mermaid fallback

If `mmdc` install fails, paste the `.mmd` content into <https://mermaid.live>, export PNG manually, drop into `output/`.
