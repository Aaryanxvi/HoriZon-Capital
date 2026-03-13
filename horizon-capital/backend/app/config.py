"""Application configuration via pydantic-settings (.env loading)."""

from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageBackend(str, Enum):
    LOCAL = "LOCAL"           # SQLite + in-memory bus (no infra needed)
    POSTGRES = "POSTGRES"     # PostgreSQL + Redis (production)


class SystemMode(str, Enum):
    PAPER_TRADING = "PAPER_TRADING"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    FULLY_AUTONOMOUS = "FULLY_AUTONOMOUS"


class CIOMode(str, Enum):
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
    app_secret_key: str = "changeme_generate_a_random_32_byte_hex"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "horizon"
    postgres_user: str = "horizon"
    postgres_password: str = "changeme_in_production"

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
    jwt_secret_key: str = "changeme_generate_a_random_32_byte_hex"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Default CIO credentials
    cio_default_username: str = "admin"
    cio_default_password: str = "changeme"

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

    # Risk defaults
    risk_max_drawdown_pct: float = 10.0
    risk_max_position_pct: float = 5.0
    risk_max_leverage: float = 1.0
    risk_var_limit_pct: float = 3.0

    # Trading universe
    india_symbols: str = "RELIANCE.NSE,TCS.NSE,INFY.NSE,HDFCBANK.NSE,ICICIBANK.NSE"
    us_symbols: str = "AAPL.NASDAQ,MSFT.NASDAQ,GOOGL.NASDAQ,AMZN.NASDAQ,TSLA.NASDAQ"
    crypto_symbols: str = "BTC-USD,ETH-USD"

    @property
    def all_symbols(self) -> list[str]:
        symbols = []
        for s in [self.india_symbols, self.us_symbols, self.crypto_symbols]:
            symbols.extend([x.strip() for x in s.split(",") if x.strip()])
        return symbols


settings = Settings()
