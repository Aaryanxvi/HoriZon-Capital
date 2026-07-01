# THESIS — ADDITIONS & PLACEMENT GUIDE (v2, scope-aligned)

> Purpose: catalogue modules / features present in repo but absent or under-described in `THESIS_03_MAIN.md`. Scope cross-checked against `README.md`, `project-report.md`, `IMPROVEMENTS.md`, and live source under `backend/app/`. Earlier v1 over-reached into items the project does not claim (DRL, HMM, Docker, Prometheus, deep frontend); v2 cuts those to future-work mentions and adds the **sentiment module**, **feature engine**, **fallback logic**, **setup wizard**, **named 4-debater roster** that v1 missed.

End-goal anchor (from `project-report.md` §1): *"Horizon Capital, a simulation-only paper trading platform built as a college project. It does not connect to any real brokerage or use real money."*

---

## 0. Reconciliations (do FIRST — single source of truth)

Verify before any narrative edit. Patch existing thesis numbers to match code:

| Field | Thesis says | Code / docs say | Action |
|---|---|---|---|
| DB tables | 28 | 28 (`grep CREATE TABLE local_storage.py`) ✓ | KEEP 28; README's "23" is outdated |
| Strategy sleeves | 4 (HRP/Faber/GapFade/MomentumRank) | 4 (verified `strategy_agent.py`) ✓ | KEEP |
| Tests | 368 | 302 (MEMORY 2026-03-31, project-report) | PATCH thesis → 302 (or rerun pytest and use fresh count) |
| Debaters | unspecified in thesis | 4 named: STRATEGY / RISK / SENTIMENT / PORTFOLIO (`debate_engine.py:DEBATER_ROLES`) | ADD roster table |
| Operating modes | implied | 3: PAPER / HUMAN_APPROVAL / FULLY_AUTONOMOUS | ADD §4.7a (below) |
| Indian feed | "Zerodha" implied real | mock feed (README); Zerodha stub uncertified | DOWNGRADE wording |
| Tone | "institutional", "production-ready 6.5/10" | "college project, simulation-only, no real money" | DIAL DOWN |

---

## 1. Cuts from v1 — REMOVED to match scope

These v1 sections OVERSHOT project end-goal. Do **not** insert. Reference as one-line future-work bullets only:

- ~~§4.10 ML training pipeline (HMM + DRL)~~ → drop section; one bullet in §6.2: *"Train HMM regime detector and DRL allocator from `ml_training/` artefacts."*
- ~~§4.9 REST + frontend deep-dive~~ → keep §3.8 router inventory only; drop WebSocket sequence + React stack
- ~~§F: Prometheus, Docker/K8s, cost ceilings, provider failover, broker certification~~ → consolidate into 3 future-work bullets
- ~~Fig 4.8 ws_sequence, Fig 4.9 ml_pipeline~~ → drop from required figures
- ~~§B.2 lit survey on Hamilton HMM and Jiang DRL~~ → drop entirely
- ~~Objective 5 in v1 (LLM abstraction as standalone objective)~~ → fold into existing Objective 4

---

## 2. ADDITIONS to Chapter 1 — Introduction

### 2.1 §1.4 Scope — patch wording

Replace current out-of-scope item 1: *"Real-money order routing… Zerodha and Alpaca interfaces are stubbed but not certified for live use"*. Add explicit honesty:

> The Indian-equity feed used in the demonstration is the **mock feed** (`data_layer/mock_feed.py`); the Zerodha and Alpaca live-broker classes exist as stubs that have never been exercised against real money or real exchange connections.

Add to in-scope:

> 9. A **sentiment-analysis module** scoring news headlines via keyword matching, with optional FinancialBERT neural scoring.
> 10. A **23-indicator feature engine** powering signal generation and feature snapshots.
> 11. **Three operating modes** (`PAPER_TRADING`, `HUMAN_APPROVAL`, `FULLY_AUTONOMOUS`) selectable at boot.
> 12. **Rule-based fallback logic** so that the system runs end-to-end without any LLM API key configured.

---

## 3. ADDITIONS to Chapter 2 — Literature Survey

Minimal. Keep v1 §2.7 LLM-debate insertion (Du et al. 2023 multi-agent debate). Drop everything else.

> **§2.7 (new) — LLM-Augmented Debate.** Recent work [Du et al., *Improving Factuality and Reasoning in Language Models through Multiagent Debate*, 2023] shows adversarial debate between language models improves factuality over single-model inference. This grounds the four-role debate engine described in §4.7.

Bibliography: add Du-et-al reference; add one sentence on FinancialBERT (Araci 2019) for sentiment.

---

## 4. ADDITIONS to Chapter 3 — Project Design

### 4.1 §3.1 Module map (Table 3.1) — append rows

Append rows missing from current table (drop ML/DRL rows from v1):

| Sub-package | Purpose | Indicative classes |
|---|---|---|
| `agents/debate/` | LLM debate engine, 4 named debaters | `DebateEngine`, `ClaudeReasoner`, `MultiModelDebate` |
| `agents/executive/cio/` | CIO agent (HUMAN/AI mode) | `CIOAgent`, `CrisisDetector` |
| `agents/front_office/research/` | Research desk | `ResearchAgent` |
| `agents/front_office/investor_relations/` | IR narratives | `IRAgent` |
| `agents/middle_office/compliance/` | Regulatory checks | `ComplianceAgent` |
| `agents/middle_office/operations/` | Settlement reconciliation | `OperationsAgent` |
| `agents/middle_office/alpha_monitor.py` | Alpha-decay detection + Thompson bandit | `AlphaMonitorAgent` |
| `agents/back_office/{accounting,quant,it}/` | Daily P&L, ad-hoc queries, infra health | `AccountingAgent`, `QuantAgent`, `ITAgent` |
| `features/technical.py` | 23 technical indicators | `TechnicalFeatures` |
| `features/sentiment_features.py` | Headline sentiment scoring | `SentimentExtractor` |
| `features/volatility.py` | GARCH(1,1), realised vol | `VolatilityEstimator` |
| `services/{alert_manager,health_monitor,report_generator,backup,performance}.py` | Alerts, health, reports, backups, perf | listed |
| `data_layer/{yahoo,crypto,mock,alpaca}_feed.py` | Multi-feed adaptors | `DataManager` |
| `llm/` | Claude / Gemini / OpenAI providers + fallback | `ProviderRegistry`, `BaseProvider` |
| `tui/onboarding.py` | First-run setup wizard (`--setup`) | `OnboardingWizard` |
| `quant/` | Portfolio optimiser, regime detector | `PortfolioOptimizer`, `RegimeDetector` |
| `api/v1/` | Optional REST surface, JWT-protected | 12 routers (§3.8) |

### 4.2 §3.4 Department breakdown — split into subsections

Split current §3.4 into §3.4.1–§3.4.4 with one paragraph per dept listing each agent's cadence, subscribed channels, published channels, persisted tables.

### 4.3 New §3.6 — Feature Engine (23 indicators)

Insert after §3.5 maths, before concurrency:

> The feature engine (`backend/app/features/`) computes twenty-three technical indicators on every bar update, persisting the result to `feature_snapshots` keyed by `(symbol, exchange, timeframe)`. Indicators are grouped by family in Table 3.X.

Table 3.X — feature engine families:

| Family | Indicators |
|---|---|
| Trend | SMA(20/50/200), EMA(12/26), MACD, MACD signal, MACD hist, Ichimoku |
| Momentum | RSI(14), Stochastic %K/%D, Williams %R, ROC |
| Volatility | Bollinger Bands (upper/mid/lower), ATR(14), GARCH(1,1) σ̂ |
| Volume | OBV, VWAP, volume SMA, volume ratio |

Powered by the `ta` Python library (chosen over `ta-lib` for pure-Python install per MEMORY note re Python 3.14).

### 4.4 New §3.7 — Sentiment Analysis Module

Insert after feature engine:

> The sentiment module (`backend/app/features/sentiment_features.py` + `data_layer/news_feed.py` if present) ingests headline streams and produces two outputs persisted to `narratives` and `sentiment_aggregates`:
>
> 1. **Keyword scorer (default).** Per-headline score s ∈ [-1, +1] from a curated bullish/bearish lexicon weighted by keyword frequency.
> 2. **FinancialBERT scorer (optional).** When `SENTIMENT_USE_BERT=true`, headlines are passed through a HuggingFace FinancialBERT model [Araci 2019]; the softmax output over {positive, neutral, negative} is mapped to [-1, +1].
>
> Aggregates over rolling windows (1 h, 1 d) feed the `SENTIMENT` debater and the `AlphaMonitor`.

Mathematical: define aggregate s̄_w = Σ s_i / |W| over window W with optional engagement weighting.

### 4.5 New §3.8 — LLM Provider Abstraction + Fallback Logic

Insert as combined section:

> The `backend/app/llm/` package exposes `BaseProvider` realised by `ClaudeProvider`, `GeminiProvider`, `OpenAIProvider`. The `ProviderRegistry` reads `.env` keys and routes per-agent.
>
> **Fallback discipline.** When no API key is configured, every LLM consumer (`StrategyAgent`, `DebateAgent`, `CIOAgent`, `IRAgent`) falls through to a rule-based default coded into the same call site. Fallbacks:
>
> - StrategyAgent: emit signal payload with `explanation = "rule-based"`.
> - DebateAgent: each role votes deterministically — STRATEGY votes FOR if 12-1 momentum > 0; RISK votes AGAINST if VaR_95 > 2 %; SENTIMENT votes by aggregate sign; PORTFOLIO votes FOR if target weight is within concentration limit.
> - CIOAgent: skip LLM advisory, emit canned crisis message based on which threshold breached.
> - IRAgent: skip narrative generation.
>
> This makes the system runnable on any laptop without paid API keys, satisfying the *zero-cost setup* design constraint.

### 4.6 New §3.9 — Debate Engine and Four-Role Roster

Insert after LLM section:

> The DebateAgent runs the engine in `backend/app/agents/debate/debate_engine.py`. Four named debaters are instantiated per debate (verified at `DEBATER_ROLES`):

Table 3.X — debater roster:

| Role | Personality (system prompt summary) | Default vote rule (fallback) |
|---|---|---|
| **STRATEGY** | aggressive growth, technical signals, momentum, entry/exit timing | FOR if 12-1 mom > 0 |
| **RISK** | conservative risk manager, drawdown, volatility, tail scenarios | AGAINST if VaR_95 > 2 % |
| **SENTIMENT** | sentiment analyst, news flow, social media tone | sign of s̄_1d |
| **PORTFOLIO** | portfolio constructor, concentration, correlation, sleeve fit | FOR if Δw within limit |

Consensus rule (verbatim from code): trade approved iff at least 3 of 4 debaters vote FOR. Confidence-weighted aggregation produces `consensus_score`. Persisted to `debate_sessions` + `debate_arguments`.

### 4.7 New §3.10 — REST API Surface (light)

Inventory of 12 routers (auth, agents, cio, debate, market_data, narratives, performance, portfolio, risk, signals, trades, router) with one sentence each. JWT auth, optional, headers from env. **No** WebSocket / React deep-dive — out of scope.

---

## 5. ADDITIONS to Chapter 4 — Implementation

### 5.1 §4.1 stack — append

| Package | Role |
|---|---|
| anthropic | Claude SDK |
| google-generativeai | Gemini SDK |
| openai | OpenAI SDK |
| ta | technical indicators (pure Python, replaces ta-lib) |
| transformers + torch | optional FinancialBERT |
| python-jose | JWT |
| scikit-learn | HRP clustering |
| tenacity | retry/backoff |

### 5.2 New §4.7a — Three operating modes

Same content as v1 D.3a (kept). Insert before dashboard section:

> Three modes selected at boot via `HORIZON_MODE` (or `--mode`):
>
> **PAPER_TRADING.** Auto-execute, no human in loop.
>
> **HUMAN_APPROVAL.** Every signal that survives RiskAgent becomes an order in `PENDING_APPROVAL`; ExecutionAgent waits for `ORDER_APPROVE` event. Operator uses REPL `orders pending`, `approve <id>`, `reject <id>` (which emit `ORDER_APPROVE` / `ORDER_REJECT`).
>
> **FULLY_AUTONOMOUS.** Signals with |Δw| ≥ Δw_debate are buffered by PortfolioAgent and submitted to DebateAgent. Order emits only on `DEBATE_CONCLUSION = APPROVED` (≥3-of-4 FOR).

Mode × authority matrix (table). Reference Fig 4.X three-mode lifecycle (mermaid stub already created).

### 5.3 New §4.7b — Setup Wizard and Onboarding

Insert subsection:

> First-run UX is a one-shot interactive wizard launched by `python -m app --setup` (`tui/onboarding.py`). It prompts for: initial capital (USD/INR), default mode, optional LLM API keys, optional broker keys, dashboard refresh rate, and writes a `.env` file. Subsequent runs (`python -m app`) skip the wizard. Re-run `--setup` to reconfigure.

### 5.4 New §4.8 — CIO Agent + Crisis Detection

Same as v1 D.4 — kept (in-scope per code).

### 5.5 New §4.9 — Backtest Engine

Same as v1 D.7 — kept.

### 5.6 New §4.10 — Stress Testing Service

Same as v1 D.8 — kept.

### 5.7 §4.7 dashboard — append panels

Add description of: alerts panel, debate transcript panel, sentiment panel (live s̄_1d gauge), watchlist with sparklines, agent-status grid.

---

## 6. ADDITIONS to Chapter 5 — Experiments

### 6.1 New §5.5 — Backtest Results

Run `backtest run` for each of 4 sleeves over 2020-01-01 → 2026-04-01. Report total return, Sharpe, max DD, alpha vs SPY/NIFTY (note: alpha is real only after `IMPROVEMENTS.md` item #1 is shipped — flag explicitly if still placeholder).

### 6.2 New §5.6 — Stress Test Results

Run all 5 canned scenarios on demo-end portfolio.

### 6.3 New §5.7 — LLM Cost Profile (only if real run done)

Per-agent USD over the demo. **Mandatory disclosure:** if no live LLM run, mark figure synthetic.

### 6.4 New §5.8 — Debate Statistics

# debates triggered, mean rounds, mean consensus_score, distribution of FOR/AGAINST per role.

### 6.5 §5.4 demo numbers — provenance audit

Currently §5.4 cites Table 5.1a (10 fills) and Table 5.1b (risk metrics). **Action:** dump real `fills` and `risk_metrics` tables from a fresh demo run; replace with measured values OR add caption *"Illustrative values — replace with measured run before submission."*

---

## 7. ADDITIONS to Chapter 6 — Conclusions

### 7.1 §6.2 future work — replace v1 list with scope-aligned items

Drop v1's grandiose list. Use the actual project roadmap (`IMPROVEMENTS.md`):

- Fix alpha calculations (real Jensen's α vs NIFTY 50 / S&P 500)
- Wire benchmark feeds (`^NSEI`, `^GSPC`)
- Service-level tests
- Zerodha real-mode certification
- Macro factor signal wiring (already done per MEMORY 2026-03-27 — verify and remove if shipped)
- Strategy plugin system
- Walk-forward backtest validation
- Backtest persistence + comparison REPL (already done per MEMORY — verify)
- Train HMM regime + DRL allocator from `ml_training/` artefacts (one bullet, not a section)
- Live alert dashboard panel (already done per MEMORY — verify)

### 7.2 §6.3 closing remarks — soften

Current text: *"the artefact is sufficient to support an academic defence, a portfolio demonstration, or a recruiter walk-through; and it is structured such that any of its successor implementations can advance the audit score one item at a time"*. Keep. But strip "production-readiness 6.5/10" framing — replace with *"college-project completeness, end-to-end demonstrable, with a documented gap list for any future continuation."*

---

## 8. Mandatory disclosures

### 8.1 Synthetic-data watermarks

Every figure rendered without `--from-db` MUST carry a visible watermark: `"SYNTHETIC — illustrative values, not measured"`. Apply to all 7 matplotlib stubs in `figures/additions/py/`. Captions in thesis: include the same disclaimer until real run done.

### 8.2 Honest scope statement (§1.2 amendment)

Add sentence to problem statement:

> This work is a college academic project, simulation-only, with no real-money order routing. Performance and risk numbers reported herein are derived from a simulated broker (`PaperBroker`) executing against cached or replayed prices; they are not indicative of any live-trading outcome.

---

## 9. Figures — final list (cuts applied)

Active figure stubs in `figures/additions/`:

**Mermaid (7, was 10 — cut 3):**
- 3.7 LLM provider routing
- 3.8 Debate state machine
- 3.10 Department × agent matrix
- 3.11 Multi-currency NAV reconciliation
- 4.6 CIO crisis triggers
- 4.7 Backtest engine timing
- 4.X Three-mode order lifecycle
- ~~3.9 REST request lifecycle~~ — keep (REST in scope as light §3.10)
- ~~4.8 ws_sequence~~ — **CUT**
- ~~4.9 ml_pipeline~~ — **CUT**

**Matplotlib (5, was 7 — cut 2):**
- 5.4 Backtest equity curves per sleeve
- 5.5 Stress-test impact
- 5.7 Debate consensus histogram
- 5.8 Drawdown timeline
- 5.9 Test-pass heatmap
- ~~5.6 LLM cost stack~~ — keep ONLY if real run done; otherwise drop
- ~~5.10 Msg rate~~ — keep optional

**New figure required (not yet stubbed):**
- 3.X Sentiment pipeline mermaid (headline → keyword/BERT → narratives → aggregates → SENTIMENT debater)
- 3.X Feature engine block diagram (OHLCV → 4 indicator families → feature_snapshots)

---

## 10. Execution order

1. Patch counts (Section 0): tests 368 → 302, mark mock-Indian feed.
2. Insert sentiment + feature engine sections (4.3, 4.4) — biggest gap vs project pillars.
3. Insert debater roster table (4.6) — names matter.
4. Insert §4.7a three modes + §4.7b setup wizard.
5. Cut overshoot sections per §1.
6. Soften tone (§7.2, §8.2).
7. Add watermarks to py figure stubs.
8. Run real backtest + stress sweeps to populate §6.1, §6.2.
9. Verify MEMORY-noted recent fixes (alerts panel, macro wiring, backtest persistence) and remove from future-work if shipped.
10. Refresh prelims (LoF / LoT / Nomenclature / Abbreviations).

---

*End of additions guide v2.*
