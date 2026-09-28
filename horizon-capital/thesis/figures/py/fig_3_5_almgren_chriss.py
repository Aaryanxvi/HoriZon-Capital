# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-70C4977175DA
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Fig 3.5 — Almgren-Chriss permanent + temporary impact vs participation rate.

Constants taken verbatim from backend/app/agents/front_office/trading/paper_broker.py.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

ETA_PERM = 0.01
GAMMA_PERM = 0.5
EPSILON = 0.0001
ETA_TEMP = 0.01
GAMMA_TEMP = 0.5

PRICE = 100.0
VOL = 0.02

rho = np.logspace(-5, 0, 400)

perm = ETA_PERM * VOL * PRICE * rho ** GAMMA_PERM
temp = EPSILON * PRICE + ETA_TEMP * VOL * PRICE * rho ** GAMMA_TEMP
total = perm + temp

bps_perm = (perm / PRICE) * 10_000
bps_temp = (temp / PRICE) * 10_000
bps_total = (total / PRICE) * 10_000

fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
ax.loglog(rho, bps_perm, label="Permanent impact", linewidth=2)
ax.loglog(rho, bps_temp, label="Temporary impact (incl. half-spread)", linewidth=2)
ax.loglog(rho, bps_total, label="Total impact", linewidth=2.5, linestyle="--")
ax.axvline(0.01, color="grey", alpha=0.4, linestyle=":")
ax.axvline(0.05, color="grey", alpha=0.4, linestyle=":")
ax.text(0.011, 0.15, "1% ADV", fontsize=9, color="grey")
ax.text(0.055, 0.15, "5% ADV", fontsize=9, color="grey")

ax.set_xlabel(r"Participation rate $\rho = Q/V$", fontsize=11)
ax.set_ylabel("Impact (basis points)", fontsize=11)
ax.set_title(
    "Fig 3.5 — Almgren-Chriss impact vs. participation rate\n"
    rf"$P={PRICE}$, $\sigma={VOL}$, $\eta_p=\eta_t={ETA_PERM}$, $\gamma_p=\gamma_t=0.5$, $\epsilon=10^{{-4}}$",
    fontsize=11,
)
ax.grid(which="both", alpha=0.3)
ax.legend(loc="upper left", fontsize=10)
fig.tight_layout()

out_path = OUT / "fig_3_5_almgren_chriss.png"
fig.savefig(out_path, bbox_inches="tight")
print(f"Wrote {out_path}")
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 70C4977175DA - verify with scripts/authorship.py verify
