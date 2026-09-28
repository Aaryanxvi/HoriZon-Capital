# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-C4BEACE012DC
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Generate Horizon Capital Major Project Presentation PDF."""

from fpdf import FPDF


class PresentationPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.set_auto_page_break(auto=False)

    def add_slide(self):
        self.add_page()
        # Red bottom bar
        self.set_fill_color(200, 16, 46)
        self.rect(0, self.h - 12, self.w, 12, "F")
        # Slide number
        self.set_font("Helvetica", "", 10)
        self.set_text_color(255, 255, 255)
        self.set_xy(self.w - 20, self.h - 10)
        self.cell(10, 6, str(self.page_no()), align="C")
        # Reset text color
        self.set_text_color(0, 0, 0)

    def slide_title(self, title):
        self.set_font("Helvetica", "B", 28)
        self.set_text_color(0, 0, 0)
        self.set_xy(20, 18)
        self.cell(0, 14, title, align="C")

    def section_header(self, text, x=20, y=None):
        if y:
            self.set_y(y)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(0, 0, 0)
        self.set_x(x)
        self.cell(0, 8, text)
        self.ln(10)

    def body_text(self, text, x=20, bold=False, size=11):
        style = "B" if bold else ""
        self.set_font("Helvetica", style, size)
        self.set_text_color(50, 50, 50)
        self.set_x(x)
        self.multi_cell(self.w - 2 * x, 6, text)

    def bullet(self, text, x=25, bold_prefix=""):
        self.set_x(x)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        bullet_char = "\u2022"
        if bold_prefix:
            self.cell(5, 6, bullet_char + " ")
            xp = self.get_x()
            self.set_font("Helvetica", "B", 10)
            self.cell(self.get_string_width(bold_prefix) + 1, 6, bold_prefix)
            self.set_font("Helvetica", "", 10)
            rest = text[len(bold_prefix):] if text.startswith(bold_prefix) else " " + text
            self.multi_cell(self.w - self.get_x() - 20, 6, rest)
        else:
            self.multi_cell(self.w - 2 * x, 6, f"{bullet_char} {text}")

    def table_row(self, cols, widths, bold=False, fill=False):
        style = "B" if bold else ""
        self.set_font("Helvetica", style, 8)
        if fill:
            self.set_fill_color(220, 220, 220)
        x_start = self.get_x()
        y_start = self.get_y()
        max_h = 0
        # Calculate heights
        cell_texts = []
        for i, (col, w) in enumerate(zip(cols, widths)):
            # Estimate lines
            lines = self.multi_cell(w - 2, 5, col, split_only=True)
            h = len(lines) * 5 + 2
            if h > max_h:
                max_h = h
            cell_texts.append(lines)
        # Draw cells
        for i, (lines, w) in enumerate(zip(cell_texts, widths)):
            x = x_start + sum(widths[:i])
            self.rect(x, y_start, w, max_h)
            if fill:
                self.rect(x, y_start, w, max_h, "F")
                self.rect(x, y_start, w, max_h, "D")
            self.set_xy(x + 1, y_start + 1)
            for line in lines:
                self.set_x(x + 1)
                self.cell(w - 2, 5, line)
                self.ln(5)
        self.set_y(y_start + max_h)


def build_pdf():
    pdf = PresentationPDF()

    # ===================== SLIDE 1: TITLE =====================
    pdf.add_slide()
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_xy(20, 30)
    pdf.multi_cell(
        pdf.w - 40, 14,
        "Horizon Capital: An Autonomous AI-Powered\nHedge Fund Platform with Multi-Agent\nDebate Consensus",
        align="C",
    )
    pdf.set_font("Helvetica", "", 14)
    pdf.set_xy(20, 78)
    pdf.cell(0, 8, "Sem VI & VII Major Project", align="C")
    pdf.ln(10)
    pdf.cell(0, 8, "Department of Computer Engineering", align="C")
    pdf.ln(16)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Mentored by Dr [Your Mentor's Name]", align="C")
    pdf.ln(14)
    pdf.set_font("Helvetica", "", 13)
    pdf.cell(0, 7, "[Your Name]", align="C")
    pdf.ln(7)
    pdf.cell(0, 7, "[Team Member Names]", align="C")

    # ===================== SLIDE 2: PROBLEM DEFINITION =====================
    pdf.add_slide()
    pdf.slide_title("Problem Definition")
    pdf.set_y(38)
    pdf.body_text(
        "Algorithmic trading systems are increasingly dominant in financial markets, yet most retail and "
        "mid-tier institutional investors lack access to intelligent, multi-agent decision-making frameworks "
        "that combine quantitative analysis with AI-driven reasoning. Existing trading platforms rely on "
        "single-strategy models that fail to adapt to changing market regimes, leading to significant "
        "drawdowns during volatility shifts and regime transitions.",
        size=10,
    )
    pdf.ln(4)
    pdf.section_header("Existing Challenges")
    pdf.bullet(
        "No unified multi-agent collaboration \u2014 most systems use isolated strategies without "
        "cross-validation or debate-based consensus",
        bold_prefix="No unified multi-agent collaboration",
    )
    pdf.bullet(
        "Poor regime adaptability \u2014 static strategies fail during regime transitions "
        "(bull to bear, low to high volatility)",
        bold_prefix="Poor regime adaptability",
    )
    pdf.bullet(
        "Fragmented data sources \u2014 market data from multiple brokers (India NSE/BSE, US "
        "NYSE/NASDAQ, Crypto) remains siloed and underutilized",
        bold_prefix="Fragmented data sources",
    )
    pdf.bullet(
        "Limited risk governance \u2014 lack of real-time kill switches, VaR monitoring, and "
        "autonomous circuit breakers",
        bold_prefix="Limited risk governance",
    )
    pdf.bullet(
        "Opaque decision-making \u2014 no audit trail or explainability for why trades are executed",
        bold_prefix="Opaque decision-making",
    )
    pdf.ln(3)
    pdf.section_header("Need for the Proposed Solution")
    pdf.bullet(
        "Multi-agent AI system where specialized agents debate and reach consensus before executing trades",
        bold_prefix="Multi-agent AI system",
    )
    pdf.bullet(
        "Regime-aware strategy switching using Hidden Markov Models (HMM) to detect market state transitions",
        bold_prefix="Regime-aware strategy switching",
    )
    pdf.bullet(
        "Production-grade risk management with VaR, Conditional VaR, kill switches, and pre-trade validation",
        bold_prefix="Production-grade risk management",
    )
    pdf.bullet(
        "Transparent, auditable decision pipeline with full debate history and per-trade attribution",
        bold_prefix="Transparent, auditable decision pipeline",
    )

    # ===================== SLIDE 3: LITERATURE REVIEW =====================
    pdf.add_slide()
    pdf.slide_title("Literature Review")
    pdf.set_y(38)

    widths = [70, 90, 90]
    pdf.set_x(25)
    pdf.table_row(
        ["Broad Research Area", "Gaps Identified from Literature", "Proposed Solution in This Work"],
        widths, bold=True, fill=True,
    )
    pdf.set_x(25)
    pdf.table_row(
        [
            "1. Multi-Agent Systems in Algorithmic Trading",
            "- Existing multi-agent systems lack structured consensus mechanisms\n"
            "- Limited use of LLMs for financial reasoning\n"
            "- No debate-based decision architecture",
            "Developing a 4-agent debate engine powered by Claude AI with structured "
            "argument rounds, JSON vote parsing, and consensus calculation",
        ],
        widths,
    )
    pdf.set_x(25)
    pdf.table_row(
        [
            "2. Market Regime Detection & Adaptive Strategies",
            "- Most systems use static strategy allocation\n"
            "- HMM-based regime detection not integrated with real-time switching\n"
            "- Limited drift detection for regime transitions",
            "Implementing HMM regime detection + LFR drift detection that automatically "
            "routes signals through appropriate strategies (Momentum, Mean Reversion, "
            "Volatility, Crisis Alpha)",
        ],
        widths,
    )
    pdf.set_x(25)
    pdf.table_row(
        [
            "3. Risk Management & Portfolio Optimization",
            "- Retail platforms lack institutional-grade risk controls\n"
            "- VaR and CVaR not commonly applied in automated systems\n"
            "- No real-time kill switch mechanisms",
            "Designing an institutional-grade risk framework with VaR (95%/99%), "
            "Conditional VaR, Kelly criterion sizing, drawdown-based kill switch, "
            "and pre-trade compliance validation",
        ],
        widths,
    )

    pdf.set_font("Helvetica", "I", 10)
    pdf.set_x(25)
    pdf.ln(4)
    pdf.set_x(80)
    pdf.cell(0, 6, "Table 1. Literature Review Summary")

    # ===================== SLIDE 4: SCOPE OF PROJECT =====================
    pdf.add_slide()
    pdf.slide_title("Scope of Project")

    # Left column - Functional
    pdf.set_y(38)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(130, 8, "Functional Requirements")
    # Right column - Non-Functional
    pdf.set_x(155)
    pdf.cell(130, 8, "Non-Functional Requirements")
    pdf.ln(12)

    func_reqs = [
        ("1. Multi-Source Market Data Ingestion", " - Collects real-time and historical OHLCV data from Yahoo Finance, Alpaca, Zerodha, Polygon.io, CoinGecko, and forex APIs."),
        ("2. Feature Engineering & Technical Analysis", " - Computes 20+ technical indicators (RSI, MACD, Bollinger Bands, ATR, GARCH) and sentiment features (FinancialBERT + NewsAPI)."),
        ("3. Multi-Agent Debate & Consensus", " - 4 specialized AI agents (Strategy, Risk, Sentiment, Portfolio) debate trade decisions using Claude AI with structured voting."),
        ("4. Autonomous Trade Execution", " - Supports Paper Trading, Human Approval, and Fully Autonomous modes across Indian equities, US equities, and crypto."),
        ("5. Rich Terminal Dashboard & REPL", " - Live TUI dashboard with 30+ interactive commands for monitoring, backtesting, stress testing, and CIO governance."),
    ]
    nonfunc_reqs = [
        ("1. Scalability", " - Supports multiple asset classes, multiple brokers, and extensible strategy plugins."),
        ("2. Resilience & Fault Tolerance", " - Circuit breakers on all external APIs, worker auto-restart supervision, exponential retry with jitter."),
        ("3. Security", " - JWT authentication, password validation, startup secret warnings, CORS configuration, security headers."),
        ("4. Performance", " - Near real-time data processing with 2fps TUI refresh, in-memory message bus for low-latency agent communication."),
        ("5. Zero-Infrastructure Local Mode", " - Runs entirely on SQLite + in-memory bus with no Docker, PostgreSQL, or Redis required."),
    ]

    y_start = pdf.get_y()
    for title, desc in func_reqs:
        pdf.set_x(15)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(130, 5, title)
        pdf.ln(5)
        pdf.set_x(15)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.multi_cell(130, 4.5, desc.strip(" -"))
        pdf.ln(2)

    y_end_left = pdf.get_y()
    pdf.set_y(y_start)
    for title, desc in nonfunc_reqs:
        pdf.set_x(155)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(130, 5, title)
        pdf.ln(5)
        pdf.set_x(155)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.multi_cell(130, 4.5, desc.strip(" -"))
        pdf.ln(2)

    # ===================== SLIDE 5: DATASET DESCRIPTION =====================
    pdf.add_slide()
    pdf.slide_title("Dataset Description")
    pdf.set_y(36)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_x(25)
    pdf.cell(0, 6, "Data sourced from multiple financial market APIs and providers")
    pdf.ln(10)

    widths5 = [45, 50, 70, 85]
    pdf.set_x(25)
    pdf.table_row(
        ["Name", "Source", "Key Parameters", "Description / Purpose"],
        widths5, bold=True, fill=True,
    )
    pdf.set_x(25)
    pdf.table_row(
        [
            "Market OHLCV Data",
            "Yahoo Finance, Alpaca, Polygon.io",
            "Open, High, Low, Close, Volume,\nAdjusted Close, Timestamps",
            "Historical and real-time price data for equities (NSE/BSE, NYSE/NASDAQ) used for technical analysis and backtesting",
        ],
        widths5,
    )
    pdf.set_x(25)
    pdf.table_row(
        [
            "Crypto Market Data",
            "CoinGecko API",
            "Price, Market Cap, 24h Volume,\nPrice Change %, Supply metrics",
            "Cryptocurrency price feeds for BTC, ETH and other digital assets enabling cross-asset strategy execution",
        ],
        widths5,
    )
    pdf.set_x(25)
    pdf.table_row(
        [
            "Sentiment & News Data",
            "NewsAPI, Reddit (PRAW)",
            "Article text, sentiment scores,\npublication timestamps,\nsocial engagement metrics",
            "Financial news and social media data processed through FinancialBERT NLP for sentiment features and narrative lifecycle tracking",
        ],
        widths5,
    )
    pdf.set_x(25)
    pdf.table_row(
        [
            "Macroeconomic Data",
            "Public APIs / Manual feeds",
            "Interest rates, yield curve\nspreads, credit spreads, VIX",
            "Macro factor inputs for regime detection and risk assessment across market scopes (India, US, Global)",
        ],
        widths5,
    )

    pdf.set_font("Helvetica", "I", 10)
    pdf.ln(4)
    pdf.set_x(90)
    pdf.cell(0, 6, "Table 2. Dataset Description")

    # ===================== SLIDE 6: TECHNICAL REQUIREMENTS =====================
    pdf.add_slide()
    pdf.slide_title("Technical Requirements")
    pdf.set_y(38)

    # Left side - workflow
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_x(15)
    pdf.cell(80, 6, "Data Sources")
    pdf.set_x(105)
    pdf.cell(80, 6, "Processing Pipeline")
    pdf.set_x(200)
    pdf.cell(80, 6, "ML/AI Implementation")
    pdf.ln(8)

    sources = [
        "Yahoo Finance (Global Equities)",
        "Alpaca (US Paper + Live)",
        "Zerodha Kite (India NSE/BSE)",
        "CoinGecko (Cryptocurrency)",
        "NewsAPI / Reddit (Sentiment)",
        "Macro APIs (Rates, VIX)",
    ]
    pipeline = [
        "Data Collection & Normalization",
        "Feature Engineering (20+ indicators)",
        "Regime Detection (HMM + Drift)",
        "Agent Orchestration & Messaging",
        "Risk Validation & Compliance",
        "Debate Consensus & Execution",
    ]
    ml_impl = [
        "HMM (Regime Detection)",
        "FinancialBERT (Sentiment NLP)",
        "GARCH (Volatility Modeling)",
        "Claude AI (Debate Reasoning)",
        "Thompson Sampling (Strategy)",
        "Kelly Criterion (Position Sizing)",
    ]

    pdf.set_font("Helvetica", "", 9)
    for i in range(6):
        pdf.set_x(15)
        pdf.cell(85, 7, f"\u2022 {sources[i]}")
        pdf.set_x(105)
        pdf.cell(90, 7, f"\u2022 {pipeline[i]}")
        pdf.set_x(200)
        pdf.cell(80, 7, f"\u2022 {ml_impl[i]}")
        pdf.ln(7)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_x(15)
    pdf.cell(0, 6, "Technology Stack:")
    pdf.ln(8)

    tech_items = [
        ("Backend:", "Python, FastAPI, Uvicorn, SQLAlchemy"),
        ("Database:", "SQLite (Local) / PostgreSQL (Prod)"),
        ("Messaging:", "Redis Pub/Sub / In-Memory Bus"),
        ("Terminal UI:", "Rich (Live Dashboard, 2fps)"),
        ("AI/ML:", "Anthropic Claude, hmmlearn, FinancialBERT"),
        ("Data:", "pandas, numpy, yfinance, httpx"),
        ("Frontend:", "React 18, TypeScript, Vite, Tailwind"),
        ("Testing:", "pytest (300+ tests), Ruff linter"),
    ]
    pdf.set_font("Helvetica", "", 9)
    col1 = tech_items[:4]
    col2 = tech_items[4:]
    y_tech = pdf.get_y()
    for label, val in col1:
        pdf.set_x(20)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(25, 6, label)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(100, 6, val)
        pdf.ln(6)
    pdf.set_y(y_tech)
    for label, val in col2:
        pdf.set_x(155)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(22, 6, label)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(100, 6, val)
        pdf.ln(6)

    pdf.set_font("Helvetica", "I", 10)
    pdf.ln(2)
    pdf.set_x(80)
    pdf.cell(0, 6, "Fig 1. Technical Workflow and System Components")

    # ===================== SLIDE 7: OVERVIEW / ARCHITECTURE =====================
    pdf.add_slide()
    pdf.slide_title("Overview of Project")
    pdf.set_y(36)

    # Three columns
    col_w = 82
    col_gap = 5
    box_h = 120
    x1 = 15
    x2 = x1 + col_w + col_gap
    x3 = x2 + col_w + col_gap

    # Column headers with colored backgrounds
    header_h = 10
    # Data Ingestion (blue)
    pdf.set_fill_color(66, 133, 244)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(x1, 40)
    pdf.cell(col_w, header_h, "Data Ingestion", align="C", fill=True)

    # Intelligence Core (green)
    pdf.set_fill_color(52, 168, 83)
    pdf.set_xy(x2, 40)
    pdf.cell(col_w, header_h, "Intelligence & Processing Core", align="C", fill=True)

    # Consumption (orange)
    pdf.set_fill_color(234, 134, 0)
    pdf.set_xy(x3, 40)
    pdf.cell(col_w, header_h, "Consumption & Insights", align="C", fill=True)

    pdf.set_text_color(50, 50, 50)
    pdf.set_font("Helvetica", "", 9)

    # Data ingestion items
    di_items = [
        "Yahoo Finance (Global Equities)",
        "Alpaca (US Paper + Live Trading)",
        "Zerodha Kite (India NSE/BSE F&O)",
        "CoinGecko (Cryptocurrency)",
        "Polygon.io (Premium US Data)",
        "NewsAPI (Financial News)",
        "Reddit PRAW (Social Sentiment)",
        "Forex APIs (FX Rates)",
        "Macro Factors (Rates, VIX)",
    ]
    y_items = 54
    for item in di_items:
        pdf.set_xy(x1 + 2, y_items)
        pdf.cell(col_w - 4, 5.5, f"\u2022 {item}")
        y_items += 5.5

    # Intelligence core items
    core_sections = [
        ("Feature Engineering", ["Data Normalization", "20+ Technical Indicators", "GARCH Volatility", "Sentiment Features (NLP)"]),
        ("Multi-Agent Debate (Claude AI)", ["Strategy Debater", "Risk Debater", "Sentiment Debater", "Portfolio Debater"]),
        ("Risk & Compliance", ["VaR (95%/99%) + CVaR", "Kill Switch + Circuit Breakers", "Kelly Criterion Sizing", "Pre-Trade Validation"]),
    ]
    y_core = 54
    for section_title, items in core_sections:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(x2 + 2, y_core)
        pdf.cell(col_w - 4, 5.5, section_title)
        y_core += 6
        pdf.set_font("Helvetica", "", 8)
        for item in items:
            pdf.set_xy(x2 + 5, y_core)
            pdf.cell(col_w - 8, 4.5, f"\u2022 {item}")
            y_core += 4.5
        y_core += 2

    # Consumption items
    cons_sections = [
        ("Rich Terminal Dashboard", ["Live Agent Status Panels", "Signal & Regime Display", "Portfolio & Risk View", "2fps Real-Time Refresh"]),
        ("REPL Commands (30+)", ["backtest, stress-test", "alerts, report, health", "portfolio, performance", "CIO governance chat"]),
        ("Pixel Agent Visualizer", ["Animated ASCII Office", "Color-Coded Departments", "Activity State Bubbles"]),
    ]
    y_cons = 54
    for section_title, items in cons_sections:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(x3 + 2, y_cons)
        pdf.cell(col_w - 4, 5.5, section_title)
        y_cons += 6
        pdf.set_font("Helvetica", "", 8)
        for item in items:
            pdf.set_xy(x3 + 5, y_cons)
            pdf.cell(col_w - 8, 4.5, f"\u2022 {item}")
            y_cons += 4.5
        y_cons += 2

    # Arrows between columns
    pdf.set_draw_color(100, 100, 100)
    pdf.set_line_width(0.5)
    arrow_y = 85
    pdf.line(x1 + col_w, arrow_y, x2, arrow_y)
    pdf.line(x2 + col_w, arrow_y, x3, arrow_y)

    # Bottom bar - Infrastructure
    pdf.set_fill_color(52, 73, 94)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    infra_y = 140
    pdf.set_xy(x1, infra_y)
    pdf.cell(x3 + col_w - x1, 8, "Infrastructure: SQLite/PostgreSQL  |  Redis/MemoryBus  |  Circuit Breakers  |  Worker Supervision  |  JWT Auth  |  Structured Logging", align="C", fill=True)

    # Security bar
    pdf.set_fill_color(41, 128, 185)
    pdf.set_xy(x1, infra_y + 9)
    pdf.cell(x3 + col_w - x1, 8, "Security & Governance: JWT Authentication  |  Password Validation  |  CORS  |  Security Headers (HSTS)  |  Startup Secret Warnings", align="C", fill=True)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_xy(80, infra_y + 22)
    pdf.cell(0, 6, "Fig 2. Overall System Architecture")

    # ===================== SLIDE 8: SCHEDULE =====================
    pdf.add_slide()
    pdf.slide_title("Schedule for Sem VI")
    pdf.set_y(38)

    schedule = [
        ("Project Planning", "15/01/26", "30/01/26", True),
        ("  Project proposal & title approval", "15/01/26", "30/01/26", False),
        ("  Literature survey (multi-agent, regime, risk)", "23/01/26", "27/01/26", False),
        ("  Approved project title", "30/01/26", "30/01/26", False),
        ("Core Infrastructure Development", "01/02/26", "15/02/26", True),
        ("  Message bus & agent base framework", "01/02/26", "05/02/26", False),
        ("  Multi-source data ingestion", "06/02/26", "10/02/26", False),
        ("  Feature engineering (20+ indicators)", "11/02/26", "15/02/26", False),
        ("Agent System & Debate Engine", "16/02/26", "28/02/26", True),
        ("  Strategy agents (Momentum, MR, Vol, Crisis)", "16/02/26", "22/02/26", False),
        ("  Claude AI debate engine & consensus", "23/02/26", "28/02/26", False),
        ("Mid-Term Evaluation", "17/03/26", "20/03/26", True),
        ("  Mid-term presentation & demo", "17/03/26", "20/03/26", False),
        ("Production Hardening & Advanced Features", "21/03/26", "10/04/26", True),
        ("  Risk management (VaR, kill switch, breakers)", "21/03/26", "28/03/26", False),
        ("  Rich TUI dashboard & REPL commands", "29/03/26", "04/04/26", False),
        ("  Stress testing, alerts, reporting, health", "05/04/26", "10/04/26", False),
    ]

    sw = [130, 45, 45]
    pdf.set_x(30)
    pdf.table_row(["Task", "Begin Date", "End Date"], sw, bold=True, fill=True)
    for task, begin, end, is_bold in schedule:
        pdf.set_x(30)
        if is_bold:
            pdf.set_font("Helvetica", "B", 8)
        else:
            pdf.set_font("Helvetica", "", 8)
        y0 = pdf.get_y()
        # Draw manually
        pdf.rect(30, y0, sw[0], 7)
        pdf.rect(30 + sw[0], y0, sw[1], 7)
        pdf.rect(30 + sw[0] + sw[1], y0, sw[2], 7)
        pdf.set_xy(31, y0 + 1)
        pdf.cell(sw[0] - 2, 5, task)
        pdf.set_xy(30 + sw[0] + 1, y0 + 1)
        pdf.cell(sw[1] - 2, 5, begin, align="C")
        pdf.set_xy(30 + sw[0] + sw[1] + 1, y0 + 1)
        pdf.cell(sw[2] - 2, 5, end, align="C")
        pdf.set_y(y0 + 7)

    pdf.set_font("Helvetica", "I", 10)
    pdf.ln(4)
    pdf.set_x(80)
    pdf.cell(0, 6, "Fig 3. Project Schedule for Semester VI")

    # ===================== SLIDE 9: REFERENCES =====================
    pdf.add_slide()
    pdf.slide_title("References")
    pdf.set_y(45)

    refs = [
        '1. Hamilton, J.D. (1989). "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle." Econometrica, 57(2), 357-384. (HMM Regime Detection)',
        '2. Rockafellar, R.T. & Uryasev, S. (2000). "Optimization of Conditional Value-at-Risk." Journal of Risk, 2(3), 21-42. (VaR & CVaR)',
        '3. MacLean, L.C., Thorp, E.O. & Ziemba, W.T. (2011). "The Kelly Capital Growth Investment Criterion." World Scientific. (Kelly Criterion Sizing)',
        '4. Araci, D. (2019). "FinBERT: Financial Sentiment Analysis with Pre-trained Language Models." (FinancialBERT NLP)',
        '5. Kirilenko, A. et al. (2017). "The Flash Crash: High-Frequency Trading in an Electronic Market." Journal of Finance. (Flash Crash Analysis)',
        '6. Lu, J. et al. (2019). "Learning under Concept Drift: A Review." IEEE TKDE. (LFR Drift Detection)',
        "7. Anthropic Claude API Documentation - Multi-agent debate reasoning",
        "8. Data Sources: Yahoo Finance, Alpaca Markets, Zerodha Kite, CoinGecko, Polygon.io, NewsAPI",
    ]

    for ref in refs:
        pdf.set_x(25)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(pdf.w - 50, 6, ref)
        pdf.ln(3)

    # Save
    out_path = r"C:\Users\Admin\Documents\Code\Horizon Capital\Horizon_Capital_Presentation.pdf"
    pdf.output(out_path)
    print(f"PDF saved to: {out_path}")


if __name__ == "__main__":
    build_pdf()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token C4BEACE012DC - verify with scripts/authorship.py verify
