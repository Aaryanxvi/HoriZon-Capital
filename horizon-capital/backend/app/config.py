"""Application configuration via pydantic-settings (.env loading)."""

import secrets
from enum import StrEnum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _generate_secret() -> str:
    """Generate a cryptographically secure random hex key."""
    return secrets.token_hex(32)


class StorageBackend(StrEnum):
    LOCAL = "LOCAL"           # SQLite + in-memory bus (no infra needed)
    POSTGRES = "POSTGRES"     # PostgreSQL + Redis (production)


class SystemMode(StrEnum):
    PAPER_TRADING = "PAPER_TRADING"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    FULLY_AUTONOMOUS = "FULLY_AUTONOMOUS"


class CIOMode(StrEnum):
    HUMAN = "HUMAN"     # User acts as CIO via interactive chat
    AI = "AI"           # AI CIO agent runs autonomously


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    app_secret_key: str = ""
    app_debug: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @field_validator("app_secret_key", mode="before")
    @classmethod
    def _auto_generate_app_secret(cls, v: str) -> str:
        if not v or "changeme" in v:
            return _generate_secret()
        return v

    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "horizon"
    postgres_user: str = "horizon"
    postgres_password: str = ""

    @field_validator("postgres_password", mode="before")
    @classmethod
    def _auto_generate_pg_password(cls, v: str) -> str:
        if not v or "changeme" in v:
            return _generate_secret()
        return v

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # JWT
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def _auto_generate_jwt_secret(cls, v: str) -> str:
        if not v or "changeme" in v:
            return _generate_secret()
        return v

    # Default CIO credentials
    cio_default_username: str = "admin"
    cio_default_password: str = ""

    @field_validator("cio_default_password", mode="before")
    @classmethod
    def _auto_generate_cio_password(cls, v: str) -> str:
        if not v or v == "changeme":
            return secrets.token_urlsafe(16)
        return v

    # Zerodha
    zerodha_api_key: str = ""
    zerodha_api_secret: str = ""
    zerodha_access_token: str = ""
    zerodha_mock_mode: bool = True

    # Alpaca
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_paper_mode: bool = True

    # Execution routing: PAPER (default, in-process simulator) | ALPACA (real
    # paper-trading REST API). ExecutionAgent falls back to PAPER if the
    # Alpaca guard fails regardless of this value — see execution_agent.py.
    execution_broker: str = "PAPER"

    # Data providers
    polygon_api_key: str = ""
    newsapi_api_key: str = ""

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "horizon-capital:v1.0"

    # LLM providers (user-provided API keys)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""

    # Department AI routing: which provider each department uses.
    # Values: "auto" (any available), "claude", "openai", "gemini", "none"
    ai_front_office: str = "auto"
    ai_middle_office: str = "auto"
    ai_back_office: str = "auto"
    ai_executive: str = "auto"

    # Debate role pinning: which provider argues each role.
    # Values: "auto" (round-robin) | "claude" | "openai" | "gemini"
    debate_role_strategy: str = "auto"
    debate_role_risk: str = "auto"
    debate_role_sentiment: str = "auto"
    debate_role_portfolio: str = "auto"

    # Alerts
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_email_smtp_host: str = ""
    alert_email_smtp_port: int = 587
    alert_email_from: str = ""
    alert_email_to: str = ""
    alert_email_password: str = ""

    # System
    system_mode: SystemMode = SystemMode.PAPER_TRADING
    storage_backend: StorageBackend = StorageBackend.LOCAL
    cio_mode: CIOMode = CIOMode.HUMAN

    # Initial capital (paper trading starting balance).
    # US-equities-only scope: INR bucket is zero so no Indian trades can settle.
    initial_capital_usd: float = 100_000.0
    initial_capital_inr: float = 0.0

    # LLM rate limits
    llm_max_calls_per_minute: int = 60

    # agent_messages grows unbounded (every bus publish is persisted) — ITAgent
    # prunes rows older than this on its periodic health-check loop.
    agent_messages_retention_days: int = 7

    # Risk defaults.
    # max_drawdown 25: disaster brake, not the primary DD control (vol targeting
    # + trend gates are). 10% froze the book inside the honest backtest's normal
    # drawdown range (maxDD −36.5%) — live could never track the backtest.
    # max_position 20: sleeve design puts 20% in SPY and 18%/12% in TLT/GLD;
    # a 5% cap stranded 15-30% of NAV in cash (clipped weight is discarded).
    risk_max_drawdown_pct: float = 25.0
    risk_max_position_pct: float = 20.0
    risk_max_leverage: float = 1.0
    risk_var_limit_pct: float = 3.0
    risk_daily_loss_limit_pct: float = 5.0
    risk_max_orders_per_minute: int = 10
    risk_free_rate: float = Field(
        default=0.0,
        description=(
            "Annualised risk-free rate used for Sharpe / Sortino. "
            "Single source of truth across worker, service, backtest, quant. "
            "Default 0 so backtest and live numbers agree without surprises."
        ),
    )

    # Trading universe — US equities only for now.
    # Leave india_symbols and crypto_symbols empty to disable those markets.
    # ~36 liquid names so breadth_alpha has a real cross-section to rank; suffixes
    # match research_stack's universe so that sleeve keeps working. Includes the
    # TLT/GLD defense pair + sector ETFs the research stack rotates into.
    india_symbols: str = ""
    us_symbols: str = (
        "SPY.NYSE,QQQ.NASDAQ,TLT.NASDAQ,GLD.NYSE,"
        "AAPL.NASDAQ,MSFT.NASDAQ,NVDA.NASDAQ,GOOGL.NASDAQ,AMZN.NASDAQ,META.NASDAQ,"
        "TSLA.NASDAQ,AVGO.NASDAQ,NFLX.NASDAQ,COST.NASDAQ,ORCL.NYSE,"
        "V.NYSE,MA.NYSE,JPM.NYSE,UNH.NYSE,LLY.NYSE,"
        "XOM.NYSE,XLE.NYSE,XLK.NYSE,XLF.NYSE,XLV.NYSE,XLY.NYSE,XLI.NYSE,"
        "JNJ.NYSE,ABBV.NYSE,MRK.NYSE,PG.NYSE,KO.NYSE,WMT.NYSE,HD.NYSE,CAT.NYSE,CVX.NYSE"
    )
    crypto_symbols: str = ""

    # Universe source for the live strategy agent:
    #   "config" -> the static us/india/crypto_symbols lists above (respects .env)
    #   "sp500"  -> dynamic current S&P 500 constituents (+ anchors), batched fetch
    # Default "sp500": the breadth engine was validated on ~500 names (K=25,
    # conviction 0.5) — a 36-name cross-section is an unvalidated, weaker
    # strategy. Set UNIVERSE_SOURCE=config to honor an explicit .env US_SYMBOLS.
    universe_source: str = "sp500"

    # LLM-debate cost gate. Each debate is ~8 LLM calls, so cap how many run per
    # rolling 24h — the strongest signals get the AI debate; the rest pass through
    # and trade on the quant signal (no LLM). Raise for more AI coverage, lower to
    # save tokens. debate_min_strength skips debate for weak signals entirely.
    debate_max_per_day: int = 15
    debate_min_strength: float = 0.0
    # Model used for debater roles. Blank = each provider's default. A debate is
    # ~8 calls, so the flagship model exhausts an org's tokens-per-minute quota
    # quickly and debaters start coming back 429 (they then vote ERROR and are
    # excluded from consensus). Must name a model of whichever provider serves
    # the debate — e.g. "gpt-4o-mini" for openai.
    debate_model: str = ""

    # Portfolio risk overlay (Moreira-Muir vol targeting + Faber 200d trend gate).
    # Applied by StrategyAgent to aggregated sleeve weights. OFF by default until
    # the ship gate in scripts/validate_overlay.py passes. Fail-open: any missing
    # data means scalar 1.0 (today's behavior exactly).
    overlay_enabled: bool = False
    overlay_vol_target: float = 0.15

    # Crypto sleeve (Faber 200d trend on BTC/ETH). UNVALIDATED — no pre-registered
    # gate pass. Default off. Weight is carved out of the validated equity mix
    # pro-rata (see strategy_agent.py __init__).
    crypto_sleeve_enabled: bool = False
    crypto_sleeve_weight: float = 0.10

    # Crypto auto-discovery: rank CoinGecko by market cap instead of the static
    # BTC/ETH pair. Stablecoins + wrapped/staked derivatives are excluded, and the
    # list is intersected with what the execution broker can actually fill.
    crypto_discovery_enabled: bool = False
    crypto_discovery_top_n: int = 5

    # Polymarket prediction markets. Data + paper trading need NO account (public
    # Gamma/CLOB APIs). Real trading additionally requires POLYMARKET_REAL_TRADING=true,
    # a funded Polygon USDC wallet key, and `pip install py-clob-client-v2`
    # (the v1 `py-clob-client` is archived — CLOB v2 rejects the orders it signs).
    polymarket_markets: str = ""  # comma-separated market slugs; empty = feature off
    polymarket_real_trading: bool = False
    polymarket_private_key: str = ""
    polymarket_funder_address: str = ""
    # CLOB signature type: 0 = EOA signs for itself, 1 = email/magic proxy wallet,
    # 2 = browser-wallet proxy. Wrong value signs for the wrong address and every
    # order comes back rejected, so it must match how the funder wallet was made.
    polymarket_signature_type: int = 1

    # Polymarket sleeve — UNVALIDATED (no gate pass). Default off. Run
    # scripts/backtest_polymarket.py and pass a pre-registered gate before enabling.
    polymarket_sleeve_enabled: bool = False
    polymarket_sleeve_weight: float = 0.05

    # Polymarket auto-discovery: poll Gamma for the most-traded open markets
    # instead of a hand-typed slug list. Discovered slugs are unioned with
    # POLYMARKET_MARKETS, refreshed hourly, and filtered on 24h volume + how far
    # out the market resolves (a market resolving tomorrow has no 7d momentum
    # left to ride; one resolving in two years ties up capital).
    polymarket_discovery_enabled: bool = False
    polymarket_discovery_top_n: int = 10
    polymarket_discovery_min_volume_24h: float = 25_000.0
    polymarket_discovery_min_days: int = 10
    polymarket_discovery_max_days: int = 180

    # Sentiment sizing damper — UNVALIDATED signal, default off.
    sentiment_sizing_enabled: bool = False

    # Trade journal decision-chain enrichment (why a fill happened). On by
    # default; toggle at runtime via REPL `journal why on|off`.
    journal_decision_chain: bool = True

    @property
    def all_symbols(self) -> list[str]:
        symbols = []
        for s in [self.india_symbols, self.us_symbols, self.crypto_symbols]:
            symbols.extend([x.strip() for x in s.split(",") if x.strip()])
        return symbols

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")

    def validate_production_secrets(self) -> list[str]:
        """Return warnings for insecure defaults. Called at startup."""
        warnings: list[str] = []
        if not self.anthropic_api_key and not self.openai_api_key and not self.google_api_key:
            warnings.append(
                "No LLM API keys configured — debates will auto-approve signals"
            )
        if not self.alpaca_api_key and not self.zerodha_api_key:
            warnings.append(
                "No broker API keys configured — only paper trading with simulated fills"
            )
        return warnings


settings = Settings()
