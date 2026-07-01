# Horizon Capital

Autonomous AI hedge-fund, modeled as a firm org chart of LLM + rule-based agents. **Primary product is a desktop terminal trading agent** (Rich TUI + REPL). A React GUI + FastAPI API + Electron wrapper sit on top as an optional desktop app.

**Repo root:** `C:\Users\Admin\Documents\Code\Horizon Capital\horizon-capital`
**Python:** 3.14 (code targets >=3.11)

## Layout (repo root `horizon-capital/`)

| Path | What |
|------|------|
| `backend/` | The actual product. Python app under `backend/app/`. **See `backend/CLAUDE.md` for the full map.** |
| `frontend/` | React 18 + TS + Vite + Tailwind dashboard. Zustand stores, axios `/api/v1`, WS `/ws/dashboard`. 7 routes (dashboard/portfolio/agents/trades/risk/performance/cio). |
| `landing-page/` | Vanilla JS + Vite marketing site (GSAP/three.js animated hero + terminal mockup). |
| `desktop/` | **Electron** wrapper. Spawns Python backend (`backend/desktop_entry.py`, STORAGE_BACKEND=LOCAL), parses `READY:<port>`, opens frameless window at the backend (which serves `frontend/dist`). electron-builder NSIS installer. |
| `ml_training/` | Future-phase DRL (stable-baselines3, commented out) + HMM regime trainer. `artifacts/` empty — MVP is rule-based. |
| `thesis/` | B.E. undergraduate thesis (markdown + mermaid/matplotlib figure generators). |
| `infrastructure/` | docker-compose (postgres/redis/backend/frontend/nginx) — runs the FastAPI path, not the TUI. |
| `tests/` | Root test tree: `tests/unit/` (drift, features, VaR). Main suite lives in `backend/tests/`. |
| `scripts/` | Backfill, smoke, DB bootstrap, PDF doc generators. |

## Run

```bash
cd horizon-capital/backend
python -m app              # desktop terminal agent (the product)
```

GUI desktop app: `cd desktop && npm start` (needs backend built). Web dev: backend `uvicorn app.main:app` :8000 + `cd frontend && npm run dev` :3000.

## Critical facts

- The app is **`backend/app/`** — older docs that say `app/tui/...` mean `backend/app/tui/...`.
- **LOCAL mode** (default): SQLite + in-memory bus + dict KV, zero infra. POSTGRES mode: Postgres + Redis. `runtime.get_bus()` / `get_session_factory()` switch backends; Redis/asyncpg lazy-imported.
- **TA library**: `ta` (pure Python), NOT `ta-lib` (C library).
- **Type hints**: `X | None` not `Optional[X]` (UP007). Ruff line-length=100, target=py311, select=E,F,I,N,W,UP.
- **passlib** dropped (py3.14 incompat) → bcrypt directly in `core/security.py`.
- **Trading modes**: PAPER_TRADING (immediate), HUMAN_APPROVAL (REPL approve/reject), FULLY_AUTONOMOUS (debate gate — PortfolioAgent buffers signals, releases on DEBATE_CONCLUSION APPROVED).
- **Cash** is DB-backed (`cash_balances`) source of truth, KV mirrors. NAV owned only by PortfolioAgent.

## Other root files

- `HORIZON_CAPITAL_FULL_AUDIT.md`, `Horizon_Capital_Presentation.md`, `generate_presentation.py` — audit + presentation artifacts.
- `research/` — academic PDFs + LLM-trading research notes.
- `backend/*.md` (DOCUMENTATION, TECHNICAL_DEEP_DIVE, TRADING_LOGIC_DEEP_DIVE, AUDIT_*, USER_GUIDE) — deep design docs; some predate refactors, treat `backend/CLAUDE.md` as ground truth for structure.
