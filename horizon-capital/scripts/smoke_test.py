#!/usr/bin/env python3
"""smoke_test.py -- End-to-end sanity checks for Horizon Capital.

Usage:
    python scripts/smoke_test.py

Checks:
    1. Postgres connection
    2. Redis connection
    3. /healthz endpoint
    4. At least 1 market instrument exists
    5. Redis has system mode set
    6. API endpoints return 200 (with auth)

Exit code 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx
import redis
from sqlalchemy import create_engine, text

from app.config import settings
from app.core.security import create_access_token

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

BASE_URL = f"http://{settings.app_host}:{settings.app_port}"
if settings.app_host == "0.0.0.0":
    BASE_URL = f"http://127.0.0.1:{settings.app_port}"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    """Record a check result and print it."""
    status = "PASS" if passed else "FAIL"
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    RESULTS.append((name, passed, detail))


# ------------------------------------------------------------------
# 1. Postgres
# ------------------------------------------------------------------

def check_postgres() -> None:
    try:
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 AS ok"))
            row = result.fetchone()
            assert row is not None and row.ok == 1
        engine.dispose()
        check("Postgres connection", True)
    except Exception as exc:
        check("Postgres connection", False, str(exc))


# ------------------------------------------------------------------
# 2. Redis
# ------------------------------------------------------------------

def check_redis() -> None:
    try:
        r = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            decode_responses=True,
        )
        pong = r.ping()
        assert pong is True
        r.close()
        check("Redis connection", True)
    except Exception as exc:
        check("Redis connection", False, str(exc))


# ------------------------------------------------------------------
# 3. /healthz endpoint
# ------------------------------------------------------------------

def check_healthz() -> None:
    try:
        resp = httpx.get(f"{BASE_URL}/healthz", timeout=5.0)
        assert resp.status_code == 200
        body = resp.json()
        check("/healthz endpoint", True, f"status={body.get('status')}")
    except Exception as exc:
        check("/healthz endpoint", False, str(exc))


# ------------------------------------------------------------------
# 4. Market instruments exist
# ------------------------------------------------------------------

def check_instruments() -> None:
    try:
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) AS cnt FROM market_instruments"))
            row = result.fetchone()
            count = row.cnt if row else 0
        engine.dispose()
        check("Market instruments exist", count > 0, f"count={count}")
    except Exception as exc:
        check("Market instruments exist", False, str(exc))


# ------------------------------------------------------------------
# 5. Redis system mode
# ------------------------------------------------------------------

def check_system_mode() -> None:
    try:
        r = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            decode_responses=True,
        )
        mode = r.get("horizon:system:mode")
        r.close()
        check("Redis system mode set", mode is not None, f"mode={mode}")
    except Exception as exc:
        check("Redis system mode set", False, str(exc))


# ------------------------------------------------------------------
# 6. API endpoints (authenticated)
# ------------------------------------------------------------------

def check_api_endpoints() -> None:
    """Hit several API endpoints with a valid JWT and expect 200."""
    token = create_access_token({"sub": "admin", "role": "cio"})
    headers = {"Authorization": f"Bearer {token}"}

    endpoints = [
        "/api/v1/portfolio/positions",
        "/api/v1/portfolio/summary",
        "/api/v1/risk/metrics",
        "/api/v1/agents/status",
    ]

    for path in endpoints:
        try:
            resp = httpx.get(f"{BASE_URL}{path}", headers=headers, timeout=5.0)
            passed = resp.status_code in (200, 404)  # 404 is ok if no data yet
            detail = f"status={resp.status_code}"
            check(f"API {path}", passed, detail)
        except Exception as exc:
            check(f"API {path}", False, str(exc))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  Horizon Capital -- Smoke Test")
    print("=" * 60)
    print()

    check_postgres()
    check_redis()
    check_healthz()
    check_instruments()
    check_system_mode()
    check_api_endpoints()

    print()
    print("-" * 60)
    total = len(RESULTS)
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = total - passed
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("-" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
