#!/usr/bin/env bash
# bootstrap_db.sh -- Run Alembic migrations and seed initial market instruments.
#
# Usage:
#   ./scripts/bootstrap_db.sh
#
# Environment variables (optional):
#   POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

# Defaults (match app/config.py)
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-horizon}"
DB_USER="${POSTGRES_USER:-horizon}"
DB_PASS="${POSTGRES_PASSWORD:-changeme_in_production}"

export PGPASSWORD="$DB_PASS"

echo "============================================"
echo "  Horizon Capital -- Database Bootstrap"
echo "============================================"
echo ""
echo "  Host : $DB_HOST:$DB_PORT"
echo "  DB   : $DB_NAME"
echo "  User : $DB_USER"
echo ""

# ------------------------------------------------------------------
# Step 1: Run Alembic migrations
# ------------------------------------------------------------------
echo "[1/2] Running Alembic migrations ..."
cd "$BACKEND_DIR"
alembic upgrade head
echo "       Migrations complete."
echo ""

# ------------------------------------------------------------------
# Step 2: Seed market instruments
# ------------------------------------------------------------------
echo "[2/2] Seeding market instruments ..."

python3 -c "
import sys
sys.path.insert(0, '.')

from sqlalchemy import create_engine, text

DB_URL = 'postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}'
engine = create_engine(DB_URL)

instruments = [
    # NIFTY 50 top 5
    ('RELIANCE',  'NSE',    'EQUITY', 'INR', 1,   0.05),
    ('TCS',       'NSE',    'EQUITY', 'INR', 1,   0.05),
    ('INFY',      'NSE',    'EQUITY', 'INR', 1,   0.05),
    ('HDFCBANK',  'NSE',    'EQUITY', 'INR', 1,   0.05),
    ('ICICIBANK', 'NSE',    'EQUITY', 'INR', 1,   0.05),
    # S&P 500 top 5
    ('AAPL',      'NASDAQ', 'EQUITY', 'USD', 1,   0.01),
    ('MSFT',      'NASDAQ', 'EQUITY', 'USD', 1,   0.01),
    ('GOOGL',     'NASDAQ', 'EQUITY', 'USD', 1,   0.01),
    ('AMZN',      'NASDAQ', 'EQUITY', 'USD', 1,   0.01),
    ('TSLA',      'NASDAQ', 'EQUITY', 'USD', 1,   0.01),
    # Crypto
    ('BTC-USD',   'CRYPTO', 'CRYPTO', 'USD', 1,   0.01),
    ('ETH-USD',   'CRYPTO', 'CRYPTO', 'USD', 1,   0.01),
]

INSERT_SQL = text('''
    INSERT INTO market_instruments
        (id, symbol, exchange, asset_class, currency, lot_size, tick_size, is_active, created_at, updated_at)
    VALUES
        (gen_random_uuid(), :symbol, :exchange, :asset_class, :currency, :lot_size, :tick_size, true, now(), now())
    ON CONFLICT (symbol, exchange) DO NOTHING
''')

with engine.begin() as conn:
    for sym, exch, ac, cur, lot, tick in instruments:
        conn.execute(INSERT_SQL, {
            'symbol': sym,
            'exchange': exch,
            'asset_class': ac,
            'currency': cur,
            'lot_size': lot,
            'tick_size': tick,
        })

print(f'       Seeded {len(instruments)} instruments (duplicates skipped).')
engine.dispose()
"

echo ""
echo "Bootstrap complete."
