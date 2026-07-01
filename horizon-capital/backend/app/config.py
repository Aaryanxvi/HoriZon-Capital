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

    # Risk defaults
    risk_max_drawdown_pct: float = 10.0
    risk_max_position_pct: float = 5.0
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
    # Default "config" so an explicit .env US_SYMBOLS is honored. Set
    # UNIVERSE_SOURCE=sp500 to trade the full ~500-name breadth universe.
    universe_source: str = "config"

    # LLM-debate cost gate. Each debate is ~8 LLM calls, so cap how many run per
    # rolling 24h — the strongest signals get the AI debate; the rest pass through
    # and trade on the quant signal (no LLM). Raise for more AI coverage, lower to
    # save tokens. debate_min_strength skips debate for weak signals entirely.
    debate_max_per_day: int = 15
    debate_min_strength: float = 0.0

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
