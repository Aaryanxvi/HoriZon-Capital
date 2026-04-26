# LLM-Powered Trading Agent Research

**Date:** 2026-04-24
**Purpose:** Best practices from top GitHub repos, academic papers, and real-money competitions

---

## 1. Top GitHub Repositories

### Tier 1: Mega-Popular (10,000+ Stars)

**virattt/ai-hedge-fund — ~51,700 stars**
- https://github.com/virattt/ai-hedge-fund
- 18 specialized AI agents, each embodying a famous investor's philosophy (Buffett, Munger, Graham, Ackman, Cathie Wood, Burry, etc.)
- LangGraph orchestration. Shared `AgentState` dictionary — downstream agents reference upstream analysis
- 13 LLM providers with hierarchical model config (system default → global override → per-agent override)
- React + TypeScript frontend with visual drag-and-drop workflow editor (React Flow)
- Educational/research only — no real trading

**AI4Finance-Foundation/FinGPT — ~15,900 stars**
- https://github.com/AI4Finance-Foundation/FinGPT
- Open-source financial LLM, data-centric approach
- Four layers: data source aggregation, data engineering, LLM adaptation (LoRA/QLoRA fine-tuning), application
- FinGPT v3 achieves F1=87.62% on financial sentiment datasets (comparable to GPT-4)
- Fine-tuning costs under $300 per run
- FinGPT-RAG for retrieval-augmented sentiment analysis
- Columbia University + NYU Shanghai

**AI4Finance-Foundation/FinRobot**
- https://github.com/AI4Finance-Foundation/FinRobot
- Four-layer architecture: Financial AI Agents → Financial LLM Algorithms → LLMOps/DataOps → Multi-source LLM Foundation Models
- Financial Chain-of-Thought (CoT) prompting
- Market Forecasting Agents, Document Analysis Agents, Trading Strategy Agents

### Tier 2: Significant Research Projects (1,000+ Stars)

**TauricResearch/TradingAgents**
- https://github.com/TauricResearch/TradingAgents
- Academic paper: arXiv:2412.20138
- Most architecturally sophisticated multi-agent trading framework
- 7 roles: Fundamentals Analyst, Sentiment Analyst, News Analyst, Technical Analyst, Researcher, Trader, Risk Manager
- **Multi-agent debate**: bull and bear researchers argue before a judge synthesizes
- Risk team with aggressive/conservative/neutral perspectives
- Uses `deep_think_llm` for complex reasoning, `quick_think_llm` for rapid tasks
- Supports GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x
- Communication: structured reports for data + natural language for debate

**pipiku915/FinMem-LLM-StockTrading**
- https://github.com/pipiku915/FinMem-LLM-StockTrading
- Published at AAAI and IEEE
- Three modules: Profiling, Memory (layered), Decision-making
- **Layered memory** — info routed to different layers by time sensitivity
- Adjustable "cognitive span" for retaining critical information
- Demonstrated superior cumulative returns in backtests

**MingyuJ666/Stockagent**
- https://github.com/MingyuJ666/Stockagent
- Event-driven simulation: Initial, Trading, Post-Trading, Special Events phases
- Finding: different LLMs develop distinctly different trading personalities

### Tier 3: Notable Specialized Projects

- **EthanAlgoX/LLM-TradeBot** — Multi-agent crypto trading with AUTO3 symbol selection
- **guberm/polymarket-bot** — Claude ensemble for Polymarket, Kelly criterion sizing, documented real profits
- **chainstacklabs/web3-ai-trading-agent** — Stateless DeFi agent for Uniswap V4

---

## 2. Key Academic Frameworks

### ATLAS (ACL 2026)
- Adaptive Trading with LLM Agents through Dynamic Prompt Optimization
- **Adaptive-OPRO**: prompt optimization that dynamically updates agent instructions using real-time stochastic feedback
- Tested 7 LLM backbones (GPT-o3, GPT-o4-mini, Claude Sonnet 4, LLaMA 3.3-70B, Qwen3-235B)
- Key finding: Adaptive-OPRO consistently outperforms fixed prompts
- **Reflection-based reasoning can DEGRADE performance** in well-tuned systems
- Outperforms especially in volatile regimes

### QuantAgent
- First multi-agent LLM framework for high-frequency trading
- 4 agents: IndicatorAgent, PatternAgent, TrendAgent, RiskAgent
- Uses ONLY price data (OHLC) — no news or sentiment
- Achieved superior zero-shot performance across 10 instruments (BTC, Nasdaq futures)
- 4-hour intervals

---

## 3. Real-Money Competition Results

### Alpha Arena — Real $10K Crypto Trading
Six frontier LLMs, each given $10,000 real capital, crypto perpetual contracts on Hyperliquid.

| Model | Return | Win Rate | Profit |
|-------|--------|----------|--------|
| Qwen3 Max | **+22.3%** | 30.2% | $2,232 |
| DeepSeek Chat V3.1 | +4.89% | 24.4% | $489 |
| GPT-5 | Heavy losses | — | — |
| Claude 4.5 Sonnet | Losses | — | — |
| Gemini 2.5 Pro | 60%+ losses | — | — |

**Takeaway: "Best" general-purpose LLMs performed WORST. Cheaper, focused models won.**

### NexusTrade LLM Trading Battle
10 AI models competed to generate profitable strategies.

- **Winners**: MiniMax 2.5 and GPT-5-mini (cheapest models)
- GPT-5-mini's "Quality Value" strategy: profitable in EVERY training year including 2022 bear market
- **Biggest loser**: Claude Opus — most expensive, never beat S&P 500, lost 73% while market gained 45%
- For *strategy generation* (not execution), Claude Opus 4.1 scored highest (95% avg) — good at understanding strategy quality but bad at parameter optimization

### Polymarket Bots (Real Money)
- Claude ensemble turned $2,000 → $12,000 overnight
- Architecture: multi-model ensemble (GPT-4o 40%, Claude Sonnet 35%, Gemini 25%)
- Kelly criterion position sizing
- Current market price shown as Bayesian prior
- Some traders report hundreds of thousands in profits
- Costs cut from $340/mo → $136/mo by optimizing model-to-task allocation

---

## 4. Best Practices (Consensus)

### Prompt Engineering for Trading

1. **Structured output (JSON schemas) for ALL agent communication** — natural language only for debate phases
2. **Role-specific system prompts** with detailed persona descriptions
3. **Financial Chain-of-Thought** — break complex decisions into logical steps
4. **Low temperature (0.0–0.2)** for analytical/decision tasks
5. **Adaptive prompts** (ATLAS Adaptive-OPRO) — evolve based on P&L feedback
6. **Never ask LLM to calculate** — compute indicators/metrics externally, pass structured results
7. **Structured reports over dialogue** — agents submit reports to global state, not chat

### Data to Feed the LLM

- Technical indicators computed externally (RSI, MACD, SMA, Bollinger)
- Financial fundamentals (P/E, P/B, debt-to-equity, FCF, earnings)
- News sentiment (pre-scored or raw headlines for LLM classification)
- Social media sentiment (Reddit, Twitter)
- Macro data (interest rates, yield curves, inflation)
- QuantAgent proved pure price data (OHLC only) can work well

### Multi-Agent Debate Architecture

TradingAgents (most developed):
1. **Bull researcher** argues for buying
2. **Bear researcher** argues for selling
3. **Judge agent** synthesizes both into conclusion
4. **Risk team** (aggressive/conservative/neutral) evaluates
5. **Fund manager** final approval

### Hallucination Prevention

- Never let LLM calculate financial metrics — always compute externally
- RAG grounding — Time-Series Augmented Generation (TSAG) reduces hallucinations 60-80%
- JSON schemas with validation prevent inventing fields/values
- Global state with queryable facts — agents query shared state, not LLM memory
- Confidence scores + fallback workflows
- Human-in-the-loop for high-stakes decisions

### Risk Management That Works

1. **Kelly Criterion** for position sizing
2. **Dedicated Risk Agent** evaluating exposure/volatility/drawdown/liquidity before every trade
3. **Multi-perspective risk** (aggressive/conservative/neutral viewpoints)
4. **Hard drawdown limits** that halt trading
5. **Volatility-based position sizing** — equal risk contribution
6. **Circuit breakers** for extreme conditions

### Model Tiering

- `quick_think_llm` (cheap/fast) for monitoring, data retrieval, indicator computation
- `deep_think_llm` (expensive/slow) for analysis, debate, decision-making
- Multi-model ensemble with weighted averaging for final decisions

---

## 5. Common Mistakes

1. Using expensive models when cheap ones work better for trading
2. Letting LLM do math (hallucination risk)
3. Unstructured agent dialogue (info loss — use structured reports)
4. No hard risk stops (LLM trades into oblivion confidently)
5. Reflection-based reasoning degrades performance in well-tuned systems (ATLAS)
6. Single-agent systems far less reliable than multi-agent debate
7. Set-and-forget — needs continuous monitoring and prompt adaptation
8. Trusting LLM confidence — hallucinated info presented fluently
9. Overfitting to backtest data
10. Ignoring API costs — can eat into returns

---

## 6. Implications for Horizon Capital

### What We're Doing Right
- Multi-agent debate architecture (validated by TradingAgents research)
- External indicator computation (not asking LLM to calculate)
- Bull/bear debate before trade execution
- Risk agent evaluating before orders

### What to Improve
- **Adaptive-OPRO**: evolve prompts based on actual trading results
- **Layered memory** (FinMem): route info by time-sensitivity
- **Model tiering**: cheap models for most tasks, expensive for analysis only
- **Weighted multi-model ensemble** for final decisions (not single LLM)
- **Kelly Criterion** position sizing
- **Structured JSON output schemas** for all agent communication
- **Three-perspective risk team** (aggressive/conservative/neutral)
- **Low temperature (0.0–0.2)** for all trading decisions
- **Judge agent** to synthesize debate conclusions (not just majority vote)

### Key Repos to Study
- https://github.com/virattt/ai-hedge-fund (architecture reference)
- https://github.com/TauricResearch/TradingAgents (debate system reference)
- https://github.com/pipiku915/FinMem-LLM-StockTrading (memory architecture)
- https://github.com/guberm/polymarket-bot (real-money ensemble architecture)

### Key Papers
- ATLAS: arXiv (ACL 2026) — adaptive prompt optimization
- TradingAgents: arXiv:2412.20138 — multi-agent debate
- QuantAgent: arXiv:2509.09995 — HFT multi-agent
- FinMem: AAAI/IEEE — layered memory for trading
