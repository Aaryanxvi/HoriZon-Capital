# Figure stubs for THESIS_ADDITIONS.md

17 stubs total. Mermaid: 10. Matplotlib: 7.

## Mermaid (`mermaid/`)
- `fig_3_7_llm_routing.mmd` — provider abstraction
- `fig_3_8_debate_state.mmd` — debate state machine
- `fig_3_9_rest_lifecycle.mmd` — REST request flow
- `fig_3_10_dept_matrix.mmd` — department × agent
- `fig_3_11_nav_reconciliation.mmd` — multi-currency NAV
- `fig_4_6_cio_crisis.mmd` — CIO crisis triggers
- `fig_4_7_backtest_timing.mmd` — backtest engine
- `fig_4_8_ws_sequence.mmd` — frontend WebSocket
- `fig_4_9_ml_pipeline.mmd` — HMM + DRL training
- `fig_4_x_three_mode_lifecycle.mmd` — PAPER vs HUMAN_APPROVAL vs FULLY_AUTONOMOUS

## Python / matplotlib (`py/`)
- `fig_5_4_backtest_curves.py` — sleeve equity curves
- `fig_5_5_stress_impact.py` — scenario impact bars
- `fig_5_6_llm_cost.py` — per-agent LLM USD
- `fig_5_7_debate_consensus.py` — consensus histogram
- `fig_5_8_drawdown_timeline.py` — DD timeline + thresholds
- `fig_5_9_test_heatmap.py` — pytest heatmap
- `fig_5_10_msg_rate.py` — bus msg rate by type

All py stubs accept `--from-db` to pull from `backend/horizon_local.db`; fall back to synthetic.

## Render
Render mermaid via existing `thesis/figures/render_all.py` (extend SOURCE_DIR list to include `additions/mermaid/`).

Run python stubs:
```
python thesis/figures/additions/py/fig_5_4_backtest_curves.py [--from-db]
```

Output PNGs → `thesis/figures/additions/output/`.
