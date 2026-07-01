# THESIS — FRONT MATTER (No Page Numbers)

> Format: A4, Times New Roman, 12 pt, 1.5 spacing. Margins: Left 1.5″, Right 1″, Top 1.5″, Bottom 1″. Page numbers: NONE on these first three pages. Front cover to be embossed in golden colour on the bound copy.

---

## [PAGE 1 — TITLE PAGE]

<br><br><br>

<p align="center"><b>HORIZON CAPITAL</b></p>

<p align="center"><b>A MULTI-AGENT AUTONOMOUS PAPER-TRADING SYSTEM</b></p>

<p align="center"><b>WITH ALMGREN–CHRISS MARKET-IMPACT SIMULATION</b></p>

<br><br>

<p align="center"><i>A Thesis Submitted in Partial Fulfilment of the Requirements for the Degree of</i></p>

<p align="center"><b>BACHELOR OF ENGINEERING</b></p>

<p align="center"><i>in</i></p>

<p align="center"><b>ELECTRONICS AND TELECOMMUNICATION ENGINEERING</b></p>

<br><br>

<p align="center"><i>by</i></p>

<p align="center"><b>[STUDENT NAME]</b></p>

<p align="center"><b>Roll No.: [XXXX]</b></p>

<br>

<p align="center"><i>Under the guidance of</i></p>

<p align="center"><b>[GUIDE NAME]</b></p>

<br><br>

<p align="center"><b>DEPARTMENT OF ELECTRONICS AND TELECOMMUNICATION</b></p>

<p align="center"><b>[COLLEGE NAME]</b></p>

<p align="center"><b>[UNIVERSITY NAME]</b></p>

<p align="center"><b>SEMESTER VII — 2014–18 BATCH</b></p>

---

## [PAGE 2 — ABSTRACT]

### ABSTRACT

The financial markets are increasingly being shaped by algorithmic and autonomous decision-making systems. Traditional retail trading platforms expose end users only to a narrow execution window, abstracting away the strategy-generation, risk-control, portfolio-optimisation, and post-trade analytics layers that institutional desks rely upon. The objective of this thesis is to design, implement, and validate an end-to-end autonomous paper-trading system, named **Horizon Capital**, which models an entire investment firm as a federation of cooperating software agents communicating over an asynchronous message bus.

The system is implemented as a desktop terminal application (Rich-based Text User Interface and Read-Eval-Print Loop) using Python 3.14, asynchronous I/O, and an embedded SQLite store, requiring zero external infrastructure for the local mode of operation. Thirteen autonomous agents distributed across four functional departments — Front Office (Strategy, Portfolio, Execution, Investor Relations), Middle Office (Risk, Compliance, Debate, Alpha-Monitor, Operations), Back Office (Accounting, Quant, IT), and Executive (CIO) — collaborate through twenty-three semantically typed message channels and twenty-eight relational tables.

Order execution is simulated through a synthetic broker that implements the Almgren–Chriss optimal-execution market-impact model for slippage estimation, exchange-specific commission tables, and configurable stale-price rejection. Risk controls include weighted-average position limits, daily-loss kill-switches, Value-at-Risk and Conditional Value-at-Risk computation over a rolling 253-day window of portfolio returns, and a kill-switch that halts further opening of risk on a 10-percent drawdown breach. The portfolio agent supports paper, human-approval, and fully-autonomous modes, with multi-currency Net Asset Value reconciliation across USD-denominated equities, INR-denominated NSE/BSE instruments, and crypto-currency holdings.

The thesis describes the architectural design, the underlying mathematical models for slippage, position sizing, weighted-average cost basis updates, and Net Asset Value computation. It documents the experimental validation of the paper-trading subsystem through a battery of three hundred and sixty-eight automated tests and an end-to-end demonstration. Finally, it identifies forty-six concrete gaps across data ingestion, fill realism, restart safety, risk enforcement and dashboard wiring, and proposes a prioritised remediation roadmap.

The contribution of this work is a reference implementation of an institutional-grade trading topology that is fully reproducible on a single laptop, together with a critical engineering audit that quantifies its production-readiness on a six-and-a-half out of ten scale.

**Keywords:** Algorithmic Trading; Multi-Agent Systems; Almgren–Chriss; Market Microstructure; Paper Trading; Asynchronous Python; Risk Management; Portfolio Optimisation.

---

## [PAGE 3 — TABLE OF CONTENTS]

### CONTENTS

| | Title | Page |
|---|-------|------|
| | Certificate | i |
| | Declaration | ii |
| | Acknowledgement | iii |
| | List of Figures | iv |
| | List of Tables | v |
| | List of Abbreviations | vi |
| | Nomenclature | vii |
| **1** | **Introduction** | **1** |
| 1.1 | Background | 1 |
| 1.2 | Problem Statement | 3 |
| 1.3 | Motivation | 4 |
| 1.4 | Scope of the Thesis | 5 |
| 1.5 | Organisation of the Thesis | 7 |
| 1.6 | Chapter Summary | 8 |
| **2** | **Literature Survey** | **9** |
| 2.1 | Multi-Agent Systems in Finance | 9 |
| 2.2 | Optimal Execution and Market Impact | 11 |
| 2.3 | Modern Portfolio Theory and Hierarchical Risk Parity | 12 |
| 2.4 | Risk Measures: VaR and CVaR | 13 |
| 2.5 | Trend-Following and Cross-Sectional Momentum | 14 |
| 2.6 | Asynchronous Software Architecture for Trading | 15 |
| 2.7 | Objectives Defined from the Survey | 16 |
| 2.8 | Chapter Summary | 17 |
| **3** | **Project Design and Mathematical Background** | **18** |
| 3.1 | High-Level System Architecture | 18 |
| 3.2 | Message Bus Abstraction | 21 |
| 3.3 | Persistence Schema | 24 |
| 3.4 | Agent Hierarchy and Department Model | 26 |
| 3.5 | Mathematical Foundations | 30 |
| 3.5.1 | Almgren–Chriss Slippage Model | 30 |
| 3.5.2 | Weighted-Average Cost-Basis Updates | 32 |
| 3.5.3 | Portfolio NAV Reconciliation | 33 |
| 3.5.4 | Value-at-Risk and Conditional VaR | 34 |
| 3.5.5 | Position Sizing from Sleeve Weights | 35 |
| 3.6 | Concurrency and Lifecycle Model | 37 |
| 3.7 | Chapter Summary | 38 |
| **4** | **Implementation of the Paper-Trading Pipeline** | **39** |
| 4.1 | Implementation Stack | 39 |
| 4.2 | Paper Broker — Internal Mechanics | 40 |
| 4.3 | Execution Agent — Order State Machine | 43 |
| 4.4 | Risk Agent — Pre-Trade Gating | 45 |
| 4.5 | Position Monitor and Mark-to-Market | 47 |
| 4.6 | Strategy Sleeves and Signal Generation | 48 |
| 4.7 | Terminal User Interface and REPL | 50 |
| 4.8 | Chapter Summary | 51 |
| **5** | **Experimental Results and System Audit** | **52** |
| 5.1 | Test Methodology | 52 |
| 5.2 | Quantitative Code Metrics | 53 |
| 5.3 | Functional Verification of Paper Trading | 54 |
| 5.4 | End-to-End Demonstration | 55 |
| 5.5 | Critical Audit — Forty-Six Identified Gaps | 56 |
| 5.6 | Quantitative Production-Readiness Score | 60 |
| 5.7 | Chapter Summary | 61 |
| **6** | **Conclusions and Further Work** | **62** |
| 6.1 | Conclusions | 62 |
| 6.2 | Further Work | 63 |
| 6.3 | Closing Remarks | 64 |
| | **Bibliography** | **65** |
| | **Appendix A — Full Database Schema** | **67** |
| | **Appendix B — Algorithms in Pseudocode** | **69** |
| | **Publications** | **71** |

---

*End of front matter — page numbering resumes in the next document.*
