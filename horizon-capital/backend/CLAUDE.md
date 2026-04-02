# Horizon Capital — Backend

Autonomous AI hedge fund platform. **Desktop terminal agent** (Rich TUI + REPL), NOT a web app.

## Quick Start

```bash
cd backend
python -m app              # Start terminal agent (TUI + agents)
python -m app --headless   # Agents only (log output)
python -m app config       # Show configuration
python -m app --setup      # Run onboarding wizard
```

## Architecture

```
app/
├── __main__.py          # CLI entry point (TUI + REPL)
├── main.py              # FastAPI entry (web API, secondary)
├── config.py            # Pydantic settings (.env loading)
├── agents/              # 4 departments × multiple agents
│   ├── base_agent.py    # Abstract base for all agents
│   ├── departments.py   # DepartmentType enum
│   ├── department_manager.py
│   ├── front_office/    # Strategy, regime, sentiment agents
│   ├── middle_office/   # Risk, compliance, VaR calculator
│   ├── back_office/     # Operations, accounting, IT
│   └── executive/       # CIO agent, governance
├── core/
│   ├── runtime.py       # Bootstrap: get_bus(), get_session_factory(), startup/shutdown
│   ├── messaging.py     # AgentMessage + AgentBus (Redis pub/sub)
│   ├── memory_bus.py    # In-memory bus for LOCAL mode
│   ├── local_storage.py # SQLite schema (23 tables)
│   ├── kv_store.py      # MemoryKVStore / Redis KV abstraction
│   ├── resilience.py    # CircuitBreaker, retry_with_backoff, with_timeout
│   ├── security.py      # JWT, password hashing, validation
│   └── logging.py       # structlog JSON logging
├── workers/
│   ├── agent_orchestrator.py       # Agent lifecycle + worker supervision
│   ├── data_ingestion_worker.py    # Yahoo/CoinGecko/Forex polling with circuit breakers
│   ├── feature_computation_worker.py  # 23 technical + 3 volatility indicators
│   └── performance_worker.py       # Sharpe, Sortino, Calmar, alpha vs NIFTY/SPX
├── services/
│   ├── stress_testing.py    # Historical crisis scenarios (GFC, COVID, etc.)
│   ├── alert_manager.py     # Rule-based alerts (console, Telegram, email)
│   ├── model_registry.py    # ML model versioning + Thompson Sampling
│   ├── report_generator.py  # Daily/weekly/monthly portfolio reports
│   └── health_monitor.py    # System observability
├── tui/
│   ├── dashboard.py     # Rich Live dashboard (2fps)
│   ├── commands.py      # REPL command handler (30+ commands)
│   ├── cio_chat.py      # Natural language CIO interface
│   ├── pixel_agents.py  # ASCII art agent office
│   └── onboarding.py    # First-run setup wizard
├── data_layer/          # Multi-feed: Alpaca, Zerodha, Yahoo, CoinGecko, Polygon, Forex
├── backtesting/         # Walk-forward backtest engine
├── llm/                 # LLM provider registry (Claude, GPT, Gemini)
├── api/v1/              # REST endpoints (12 routers)
└── plugins/             # Strategy plugin system
```

## Storage Modes

| Mode | Database | Message Bus | KV Store | Requirements |
|------|----------|-------------|----------|-------------|
| **LOCAL** (default) | SQLite | MemoryBus | MemoryKVStore | Zero infra |
| POSTGRES | PostgreSQL | Redis pub/sub | Redis | Docker/infra |

## Key Design Decisions

- **Lazy imports**: Redis, asyncpg only imported when `POSTGRES` mode. LOCAL mode runs with zero external deps.
- **`runtime.get_bus()`**: Returns MemoryBus or AgentBus based on storage backend. No singletons.
- **`_get_session_factory()`**: Lazy pattern used in workers to avoid circular imports.
- **`X | None`** instead of `Optional[X]` (UP007 lint rule).
- **`StrEnum`** for all enums (MessageType, AlertSeverity, etc.).
- **`ta`** pure Python lib for technical analysis (not `ta-lib` C library).
- **Circuit breakers** on all external API calls (Yahoo, CoinGecko, Forex, brokers).
- **Worker supervision**: Orchestrator monitors and auto-restarts crashed workers.

## Testing

```bash
python -m pytest tests/test_smoke.py -v          # 232 smoke tests
python -m pytest tests/test_integration.py -v     # 69 integration tests
python -m pytest tests/ -v                        # All 300+ tests
```

## Linting

```bash
python -m ruff check app/     # Should be 0 errors
python -m ruff check --fix app/  # Auto-fix
```

Config in `pyproject.toml`: line-length=100, target=py311, rules: E, F, I, N, W, UP.

## Environment Variables

All configured via `.env` file or environment. Key settings:
- `STORAGE_BACKEND`: LOCAL (default) or POSTGRES
- `SYSTEM_MODE`: PAPER_TRADING (default), HUMAN_APPROVAL, FULLY_AUTONOMOUS
- `CIO_MODE`: HUMAN (default) or AI
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`: LLM providers (optional)
- `ALPACA_API_KEY/SECRET`, `ZERODHA_API_KEY/SECRET`: Broker credentials (optional)
- `CORS_ORIGINS`: Comma-separated allowed origins

## Security Notes

- Default secrets (`changeme...`) trigger startup warnings
- Password policy: min 8 chars, uppercase + lowercase + digit
- Security headers: X-Frame-Options, X-Content-Type-Options, HSTS (prod)
- Swagger/ReDoc disabled in production (`APP_ENV=production`)
- Secrets masked in `config` command output

## Version

v0.2.0 — Python >=3.11, runs on Python 3.14
