# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-4D83D498F209
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""
Render Data Sources & API Contracts as a single tall narrow page, for pasting
onto a slide. Same content as the 4-page A4 version, one continuous strip.

Run: py -3.14 scripts/data_sources_strip_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF, FontFace
from fpdf.enums import XPos, YPos
from pypdf import PdfReader, PdfWriter

# ponytail: render onto one over-tall page, then crop the unused bottom.
# fpdf2 cannot size a page to its content, pypdf can move the mediabox.
PAGE_W = 110.0
DRAFT_H = 1400.0
MARGIN = 7.0
BOTTOM_PAD = 8.0
MM_TO_PT = 72.0 / 25.4

ROOT = Path(__file__).resolve().parent.parent.parent  # outer "Horizon capital"
OUT = ROOT / "Data_Sources_API_Contracts_slim.pdf"
DRAFT = OUT.with_name("_strip_draft.pdf")

NAVY = (15, 40, 80)
TEAL = (0, 120, 130)
GRAY = (80, 80, 80)
LGRAY = (220, 220, 220)
WHITE = (255, 255, 255)
BLACK = (20, 20, 20)
CODE_BG = (245, 245, 250)
CODE_FG = (40, 40, 100)
ROW_ALT = (240, 245, 255)

FONT_DIR = Path("C:/Windows/Fonts")


class Strip(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format=(PAGE_W, DRAFT_H))
        self.set_auto_page_break(auto=False)
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.add_font("Arial", "", str(FONT_DIR / "arial.ttf"))
        self.add_font("Arial", "B", str(FONT_DIR / "arialbd.ttf"))
        self.add_font("Arial", "I", str(FONT_DIR / "ariali.ttf"))
        self.add_font("Mono", "", str(FONT_DIR / "cour.ttf"))

    @property
    def usable_w(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def rule(self, color=LGRAY, lw=0.3):
        self.set_draw_color(*color)
        self.set_line_width(lw)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.5)

    def banner(self, title: str, subtitle: str):
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 26, "F")
        self.set_y(6)
        self.set_font("Arial", "B", 15)
        self.set_text_color(*WHITE)
        self.cell(0, 8, title, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Arial", "", 8.5)
        self.set_text_color(*LGRAY)
        self.cell(0, 5, subtitle, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(32)
        self.set_text_color(*BLACK)

    def h1(self, text: str):
        self.ln(2.5)
        self.set_fill_color(*NAVY)
        self.set_text_color(*WHITE)
        self.set_font("Arial", "B", 8.5)
        self.cell(0, 6, f"  {text}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)
        self.set_text_color(*BLACK)

    def h2(self, text: str, note: str = ""):
        self.ln(1.5)
        self.set_text_color(*TEAL)
        self.set_font("Arial", "B", 7.5)
        self.cell(0, 4.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if note:
            self.set_text_color(*GRAY)
            self.set_font("Mono", "", 5.5)
            self.cell(0, 3.2, note, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.rule(TEAL, 0.35)
        self.set_text_color(*BLACK)

    def h3(self, text: str):
        self.ln(1)
        self.set_text_color(*NAVY)
        self.set_font("Arial", "B", 6.5)
        self.cell(0, 3.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*BLACK)

    def para(self, text: str):
        self.set_font("Arial", "", 6.2)
        self.set_text_color(*BLACK)
        self.multi_cell(0, 3.1, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.8)

    def label(self, tag: str, text: str):
        """One-line 'Discarded: ...' style note with a bold lead-in."""
        self.set_font("Arial", "B", 6.2)
        self.set_text_color(*GRAY)
        lead_w = self.get_string_width(tag + " ") + 0.5
        self.cell(lead_w, 3.1, tag)
        self.set_font("Arial", "", 6.2)
        self.set_text_color(*BLACK)
        self.multi_cell(self.usable_w - lead_w, 3.1, text,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.8)

    def code(self, text: str):
        lines = text.split("\n")
        h = len(lines) * 3.0 + 2.4
        self.set_fill_color(*CODE_BG)
        self.set_draw_color(*LGRAY)
        self.set_line_width(0.2)
        self.rect(self.l_margin, self.get_y(), self.usable_w, h, "DF")
        self.set_xy(self.l_margin + 1.5, self.get_y() + 1.2)
        self.set_font("Mono", "", 5.3)
        self.set_text_color(*CODE_FG)
        self.multi_cell(self.usable_w - 3, 3.0, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*BLACK)
        self.ln(1.5)

    def table(self, rows: list[list[str]], widths: tuple[int, ...]):
        self.set_font("Arial", "", 5.6)
        self.set_draw_color(*LGRAY)
        self.set_line_width(0.15)
        # fpdf2's row striping falls back to the current fill colour; reset it or a
        # preceding navy heading bleeds into the rows.
        self.set_fill_color(*ROW_ALT)
        head = FontFace(emphasis="BOLD", color=WHITE, fill_color=NAVY)
        with super().table(
            col_widths=widths,
            line_height=3.0,
            headings_style=head,
            cell_fill_color=ROW_ALT,
            cell_fill_mode="ROWS",
            padding=(0.6, 1.0),
            text_align="LEFT",
            width=self.usable_w,
        ) as t:
            for row in rows:
                r = t.row()
                for cell in row:
                    r.cell(cell)
        self.ln(1.5)


def build(d: Strip) -> None:
    d.add_page()
    d.banner("Horizon Capital", "Data Sources & API Contracts")

    # ---------------------------------------------------------------- 1
    d.h1("1.  Market Data")

    d.h2("Yahoo Finance", "yahoo_feed.py")
    d.para(
        "Primary historical OHLCV for all equities. yfinance 0.2.43. Polls every 30s at "
        "period=1d, interval=1m; skips closed exchanges."
    )
    d.code("yfinance.Ticker(symbol).history(\n    period=period, interval=interval)")
    d.table(
        [
            ["Raw Field", "Our Field", "Type"],
            ["Open / High / Low / Close", "open / high / low / close", "float"],
            ["Volume", "volume", "int"],
            ["Datetime (index)", "timestamp", "datetime (UTC)"],
            ["--", "exchange, currency, timeframe", "str"],
        ],
        (30, 40, 22),
    )
    d.label(
        "Symbol mapping:",
        "internal RELIANCE.NSE to yfinance RELIANCE.NS. 11 suffixes: .NS NSE, .BO BSE, "
        ".L LSE, .HK HKEX, .T TSE, .SS SSE, .SZ SZSE, .AX ASX, .TO TSX, .DE XETRA, "
        ".PA EURONEXT.",
    )
    d.label("Discarded:", "Dividends, Stock Splits, pre-market and after-hours data.")
    d.para('Also on Yahoo: USD/INR via Ticker("USDINR=X"), published to KV.')

    d.h2("Alpaca", "alpaca_feed.py, alpaca_quotes.py, batch_bars.py")
    d.para(
        "US equity market data and live paper-broker execution. Live on Alpaca paper -- "
        "the real-money path."
    )
    d.table(
        [
            ["Channel", "Endpoint"],
            ["Tick stream (WS)", "wss://stream.data.sandbox.alpaca.markets/v2/iex"],
            ["REST bars/quotes", "https://data.sandbox.alpaca.markets"],
            ["Live variants", "Same hosts, .sandbox removed"],
        ],
        (26, 66),
    )
    d.code(
        "WS    subscribe -> trade stream -> NormalizedTick\n"
        'REST  get_ohlcv(timeframe="1Day", limit=N)\n'
        "REST  latest trade  (fallback when socket down)"
    )
    d.label(
        "Caching:",
        "stateless quote helper with a few-second micro-cache; one bulk daily-bar fetch "
        "per session on a multi-hour TTL, so 60s polls read cache for free.",
    )
    d.label(
        "Execution guards:",
        "fills settled once at terminal state; zero-price fills rejected; ALPACA mode "
        "refused when broker equity diverges from local NAV; startup reconciliation "
        "against broker state.",
    )
    d.label(
        "Zerodha Kite:",
        "removed. Config keys and a rate-limiter bucket remain, but no Kite feed exists. "
        "The mock tick generator is gone. Alpaca replaced it.",
    )

    # ---------------------------------------------------------------- 2
    d.h1("2.  Alternative Data")

    d.h2("CoinGecko", "crypto_feed.py")
    d.para(
        "Crypto spot ticks, not OHLCV. Feed always on; crypto sleeve default-off "
        "(weight 0.10), executing through Alpaca crypto. Polls every 60s, no API key, "
        "all ids batched into one call."
    )
    d.code(
        "GET https://api.coingecko.com/api/v3/simple/price\n"
        "    ?ids=bitcoin,ethereum&vs_currencies=usd\n"
        "    &include_24hr_vol=true\n"
        "    &include_last_updated_at=true"
    )
    d.table(
        [
            ["Raw Field", "Our Field", "Notes"],
            ["usd", "last_price", "Spot price"],
            ["usd_24h_vol", "volume", "Defaults to 0"],
            ["last_updated_at", "timestamp", "Falls back to now()"],
            ["--", "symbol, exchange, currency", "BTC to BTC-USD; CRYPTO; USD"],
        ],
        (24, 34, 34),
    )
    d.label(
        "Mapped coins (10):",
        "BTC bitcoin, ETH ethereum, SOL solana, BNB binancecoin, XRP ripple, "
        "ADA cardano, DOGE dogecoin, DOT polkadot, AVAX avalanche-2, MATIC matic-network.",
    )
    d.label("Discarded:", "market cap, 24h change percent, unmapped coins.")

    d.h2("Polymarket", "polymarket_feed.py, pm_bars.py")
    d.para(
        "YES-outcome probability as a tradeable price series. Default-off: empty "
        "polymarket_markets disables it; sleeve gated separately (weight 0.05), "
        "pre-registered gate not yet passed. Polls midpoint every 60s; Gamma volume "
        "refresh throttled to hourly."
    )
    d.h3("Stage 1 -- resolve at connect, per slug")
    d.code("GET https://gamma-api.polymarket.com/markets?slug={slug}")
    d.para(
        'Takes clobTokenIds at the index where outcomes[i] == "yes". Skips closed markets '
        "and those without a YES token."
    )
    d.table(
        [
            ["Raw Field", "Our Field"],
            ["clobTokenIds[yes_idx]", "token_id -- key for all later polls"],
            ["conditionId / question / endDate", "condition_id / question / end_date"],
            ["volume24hr", "KV horizon:volume:{symbol}, hourly"],
            ],
        (40, 52),
    )
    d.h3("Stage 2 -- poll every 60s per symbol")
    d.code("GET https://clob.polymarket.com/midpoint\n    ?token_id={token_id}")
    d.para('mid becomes NormalizedTick(exchange="POLY", currency="USD").')
    d.label(
        "Symbol mapping:",
        "slug lowercased, non-alphanumerics to hyphens, collapsed, truncated to 40 chars "
        '-- "Fed-Cut-Sept 2026" to PM-fed-cut-sept-2026.POLY.',
    )
    d.label(
        "Backtest bars:",
        "yfinance cannot resolve .POLY, so daily bars come from "
        "clob.polymarket.com/prices-history. Probability is not a price, but the sleeve "
        "API wants OHLCV, so open = high = low = close = p and volume = 0.",
    )
    d.label(
        "Execution:",
        "FOK market orders via py-clob-client on Polygon. Optional dependency; real "
        "trading off by default and needs a private key plus funder address.",
    )

    # ---------------------------------------------------------------- 3
    d.h1("3.  News, Sentiment and Universe")

    d.h2("NewsAPI", "research/newsapi_client.py")
    d.code("GET https://newsapi.org/v2/everything")
    d.table(
        [
            ["Parameter", "Value"],
            ["q / from", "Symbol-derived / now minus days_back"],
            ["sortBy / language / pageSize", "publishedAt / en / 100"],
        ],
        (38, 54),
    )
    d.label("Kept:", "title, description, url, publishedAt, source.name.")
    d.label("Discarded:", "urlToImage, author, content. Returns empty without a key.")

    d.h2("Reddit PRAW", "research/reddit_client.py")
    d.para("Subreddits: r/IndiaInvestments, r/stocks, r/wallstreetbets.")
    d.code(
        "subreddit.search(base_symbol, sort=\"new\",\n"
        '                 time_filter="month", limit=50)'
    )
    d.label(
        "Kept:",
        "title, body, score, num_comments, created_utc, subreddit. Symbol stripped to "
        "base before search. Runs in a thread pool -- PRAW is sync, the app is async.",
    )

    d.h2("FinBERT", "research/finbert_scorer.py")
    d.para(
        "Model ahmedrachid/FinancialBERT-Sentiment-Analysis plus the Loughran-McDonald "
        "lexicon. Returns a label, a score from -1 to 1 (sign times probability), and a "
        "confidence. Lazy-loaded, batch-capable, degrades to keyword scoring without "
        "transformers or torch."
    )

    d.h2("Universe Sources")
    d.table(
        [
            ["Source", "Endpoint", "Use"],
            [
                "Current constituents",
                "datasets/s-and-p-500-companies CSV",
                "Live -- only what is investable today",
            ],
            ["Point-in-time", "fja05680/sp500 CSV", "Backtests -- historical membership"],
        ],
        (22, 36, 34),
    )
    d.para("Falls back to a bundled liquid list when offline.")
    d.label(
        "Honest gap:",
        "point-in-time fixes the universe, but yfinance has no prices for delisted names, "
        "so those drop out. Partial survivorship fix; the full one needs a paid vendor "
        "such as Sharadar or Norgate.",
    )

    # ---------------------------------------------------------------- inventory
    d.h1("Feed Inventory")
    d.para("Nothing else exists in the data layer.")
    d.table(
        [
            ["Feed", "Type", "Status"],
            ["Yahoo Finance", "Historical OHLCV, forex", "Active"],
            ["Alpaca WS + REST", "US equity ticks, bars, execution", "Live on paper"],
            ["CoinGecko", "Crypto spot ticks", "Feed on, sleeve off"],
            ["Polymarket", "Prediction market midpoints", "Default-off"],
            ["NewsAPI", "News articles", "Optional, key-gated"],
            ["Reddit PRAW", "Social posts", "Optional, key-gated"],
            ["S&P 500 constituents / PIT", "Universe", "Active"],
        ],
        (28, 40, 24),
    )


def main() -> None:
    doc = Strip()
    build(doc)
    used = doc.get_y() + BOTTOM_PAD
    doc.output(str(DRAFT))

    # Crop the unused bottom: PDF origin is bottom-left, so raise lower-left y.
    reader = PdfReader(str(DRAFT))
    page = reader.pages[0]
    page.mediabox.lower_left = (0, (DRAFT_H - used) * MM_TO_PT)
    writer = PdfWriter()
    writer.add_page(page)
    with open(OUT, "wb") as fh:
        writer.write(fh)
    DRAFT.unlink()

    print(f"PDF written to: {OUT}")
    print(f"Size: {PAGE_W:.0f} x {used:.0f} mm")
    assert used < DRAFT_H, "content overflowed the draft page -- raise DRAFT_H"


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 4D83D498F209 - verify with scripts/authorship.py verify
