# LLM Trading Agents — Reality Check (Verified Results Only)

**Date:** 2026-04-24
**Purpose:** Separate hype from reality. Only verified, real-money evidence.

---

## Executive Summary

No one has publicly documented sustained, verified profits from a pure LLM autonomous trading agent over 6+ months. The biggest documented money was made by speed arbitrage bots (not LLM intelligence). Every controlled academic study with real money showed universal losses.

---

## 1. Verified Real-Money Winners

### A. Polymarket Latency Arbitrage — $438K from $313

- Wallet `0x8dxd` turned $313 → ~$438,000 in one month (Dec 2025 - Jan 2026)
- Strategy: Speed arbitrage on 15-min BTC/ETH/SOL prediction markets
- Exploits lag between confirmed spot prices on Binance/Coinbase and Polymarket odds adjustment
- Win rate: 98% across 6,615 predictions
- Bet sizes: $4,000-$5,000 each
- **NOT LLM intelligence — any fast bot can do this**
- Polymarket introduced dynamic taker fees to kill this strategy

**Aggregate Polymarket bot profits (peer-reviewed):**
- IMDEA Networks Institute analyzed 86 million bets (Apr 2024 - Apr 2025)
- Algorithmic traders extracted ~$40 million in arbitrage profits
- Top 3 wallets: $4.2 million across 10,200+ bets
- Key insight: **Forecasting accuracy is largely irrelevant** — better price execution is the edge

Sources:
- https://finbold.com/trading-bot-turns-313-into-438000-on-polymarket-in-a-month/
- https://finance.yahoo.com/news/arbitrage-bots-dominate-polymarket-millions-100000888.html

### B. Alpha Arena Season 1 — Only Controlled LLM Competition

Six frontier LLMs, each given $10,000 real capital, crypto perpetual contracts on Hyperliquid. No human intervention. ~3 weeks.

| Model | Return | Final Value | Win Rate | Trades |
|-------|--------|------------|----------|--------|
| Qwen3 Max | **+22.3%** | ~$12,287 | 30.2% | 43 |
| DeepSeek V3.1 | +4.89% | ~$10,489 | 24.4% | 41 |
| Claude 4.5 Sonnet | ~+10% | ~$11,000 | — | — |
| Grok 4 | Modest | — | — | — |
| Gemini 2.5 Pro | **-47%** | ~$5,226 | — | — |
| GPT-5 | **-63%** | ~$3,734 | — | — |

- Only 2-3 of 6 models profitable
- Winner made $2,232 on $10K in ~3 weeks — good but not extraordinary
- Organizers acknowledged "deep flaws in Season 1"
- No long-term sustainability data

Sources:
- https://nof1.ai/
- https://www.iweaver.ai/blog/alpha-arena-ai-trading-season-1-results/
- https://www.panewslab.com/en/articles/07cbee36-3e6e-44ed-8e48-bef321b3fc3e

### C. NexusTrade LLM Trading Battle

10 AI models competed to generate profitable strategies.

- **Winners**: MiniMax 2.5 and GPT-5-mini (cheapest models)
- GPT-5-mini's "Quality Value" strategy: profitable in EVERY training year including 2022 bear market
- **Biggest loser**: Claude Opus — most expensive, never beat S&P 500, lost 73% while market gained 45%
- Lesson: Expensive models ≠ better trading judgment

Sources:
- https://nexustrade.io/blog/i-tested-every-major-llm-for-algorithmic-trading-there-is-one-clear-winner-20250811
- https://nexustrade.io/blog/i-launched-10-ai-models-to-battle-for-the-best-trading-strategy-the-cheaper-models-won-every-time-20260225

---

## 2. Verified Failures and Losses

### A. Arcada Labs / Harvard — Every Model Lost Money

Six frontier LLMs, $10,000 each, Kalshi and Polymarket, 57 days (Jan-Mar 2025).

- Kalshi losses: **-16% to -30.8%** (every model)
- Polymarket losses: averaged -1.1%
- Directly debunks viral social media claims

Sources:
- https://cybernews.com/ai-news/viral-ai-trading-debunk-model-lost-money-polymarket-kalshi/
- https://www.fastcompany.com/91531389/ai-traders-are-already-testing-prediction-markets-and-losing-money

### B. Individual Documented Losses

- Lobstar Wilde agent crashed, sent $250K-$441K tokens to random address
- One tester lost $35,000 across multiple bots
- Another spent $11,400 over 6 months testing 47 automated trading solutions
- Bots left unattended 48+ hours in volatile markets almost always hit stop-losses

Sources:
- https://pumpparade.medium.com/ai-trading-bots-lost-441k-in-one-error-heres-what-actually-works-and-what-doesn-t-4f04f890c189
- https://medium.com/@augustozz/i-built-a-crypto-trading-bot-and-lost-real-money-heres-why-i-m-trying-again-1ea1c352dffc

### C. Jake Nesler / Claude Code "100K" Experiment

- Gave Claude Code $100K via Alpaca — **PAPER TRADING ONLY** (not real money)
- Beat the market over one month (~7% vs market's 4.52%)
- Author himself said: **"An LLM is not intelligent. Do not risk real capital with this."**

Source: https://medium.com/@jakenesler/i-gave-claude-code-100k-to-trade-with-in-the-last-month-and-beat-the-market-ece3fd6dcebc

---

## 3. Professional AI Hedge Fund Performance

### Eurekahedge AI Hedge Fund Index (THE Benchmark)

- **Annualized returns (2009-2024): 9.8%**
- **S&P 500 same period: 13.7%**
- AI hedge funds have **underperformed** the S&P 500 over the long term
- These use traditional ML, NOT LLMs
- Management fees + AI infrastructure costs erode edge

### Major Quant Firms

| Firm | Approach | Uses LLM Autonomously? |
|------|----------|----------------------|
| Renaissance Technologies | Proprietary ML, pattern recognition | **No** |
| Two Sigma | ML + distributed computing | **No** — exploring LLMs to "widen research funnel" |
| Citadel Securities | HFT + AI | **No** — speed-based |
| D.E. Shaw | Hybrid quant/fundamental | **No** — AI for research assistance |

**None use LLMs as autonomous trading agents.** They use LLMs to assist human researchers.

Sources:
- https://www.eurekahedge.com/Indices/IndexView/Eurekahedge/683/Eurekahedge-AI-Hedge-fund-Index
- https://www.twosigma.com/articles/ai-in-investment-management-2026-outlook-part-i/

---

## 4. Academic Evidence

### What Research Shows

- **StockBench paper**: Most LLM agents fail to beat buy-and-hold. Strong bullish bias.
- **20+ year study**: Previously reported LLM advantages deteriorate significantly over broader evaluations
- **164 academic papers reviewed**: Most have unacknowledged methodological flaws (narrow timeframes, survivorship bias)
- **LLM sentiment analysis**: Sharpe ratio of 3.05 in backtests (2021-2023) — but backtests only

Sources:
- https://arxiv.org/abs/2510.02209 (StockBench)
- https://arxiv.org/html/2505.07078v1 (Long-run deterioration)
- https://arxiv.org/html/2602.14233 (Bias in finance LLM studies)

---

## 5. Regulatory Warnings

**CFTC (Commodity Futures Trading Commission):**
- "AI technology cannot predict the future or sudden market changes"
- Scammers claim AI algorithms generate "tens of thousands of percent returns" or "100% win rates"
- Generative AI makes it "increasingly easier for fraudsters to create convincing scams"

**SEC:**
- Charged crypto platforms and AI investment clubs in $14M fraud scheme (Dec 2025)

Sources:
- https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html
- https://www.cftc.gov/PressRoom/PressReleases/8854-24

---

## 6. Professional Quant Sentiment on LLM Trading

| Confidence Level | % of Quants |
|-----------------|-------------|
| Extremely confident | 4% |
| Very confident | 12% |
| Slightly confident | 36% |
| Not confident at all | 26% |

Source: https://www.ai-street.co/p/how-quants-are-evolving-with-llms

---

## 7. What Actually Makes Money (Evidence-Based)

| Approach | Evidence Level | Typical Returns |
|----------|---------------|-----------------|
| Speed arbitrage (Polymarket) | Verified on-chain | Huge but strategy gets patched |
| LLM as research assistant + human trader | Professional consensus | Modest alpha |
| LLM sentiment + traditional quant execution | Academic backtests (not live) | Sharpe ~1.0-3.0 backtested |
| Rule-based crypto bots (NOT LLM) | Multiple platforms | 12-25% annualized |
| Pure autonomous LLM trading | Alpha Arena, Arcada Labs | **Loses money** over meaningful timeframes |

---

## 8. Key Takeaways

1. **Cheaper models beat expensive ones** at trading (Qwen3, DeepSeek won; GPT-5, Claude, Gemini lost)
2. **LLMs have strong bullish bias** — profit in up markets, crash in down markets
3. **No sustained (12+ month) profitable autonomous LLM trading exists** in public record
4. **Hybrid systems work** — LLM for research/sentiment + traditional quant for execution/risk
5. **Professional AI hedge funds underperform** S&P 500 (9.8% vs 13.7% annualized over 15 years)
6. **CFTC/SEC actively warning** that AI trading bot claims are frequently fraudulent
7. **Most published academic results** have methodological flaws (narrow timeframes, survivorship bias)
8. **The money is made by**: speed arbitrageurs, people selling AI trading tools, and hybrid human+AI traders

---

## 9. Realistic Expectations

- **Rule-based crypto bots**: 12-25% annualized (well-configured)
- **AI-assisted human trading**: ~34% ROI over 6 months (one platform's data, likely cherry-picked)
- **Fully autonomous AI bots**: ~29% ROI over 6 months (same source, likely cherry-picked)
- **Spot grid trading on major crypto**: 0.5-3% monthly
- **Professional AI hedge funds**: 9.8% annualized (underperforms index)

---

## 10. Where the Real Edge Might Be

Based on all evidence, the most promising approach is:

1. **LLM for sentiment analysis and research** — this is where LLMs genuinely add value
2. **Traditional quant models for signals and execution** — proven over decades
3. **LLM for hypothesis generation** — generate strategy ideas, test with traditional backtesting
4. **Human oversight for risk management** — LLMs confidently trade into oblivion without hard stops
5. **Multi-model ensemble for forecasting** — weighted averaging across models reduces individual model failure
6. **Adaptive prompts** (ATLAS) — prompts that evolve based on actual P&L feedback
7. **Focus on structural inefficiencies** — prediction markets, crypto, illiquid instruments where edges exist
