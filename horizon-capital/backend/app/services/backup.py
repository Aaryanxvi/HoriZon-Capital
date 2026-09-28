# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D55E0ADF3EBB
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Disaster recovery and data backup service.

Automated SQLite backup, position snapshot export, and state recovery
on crash. Ensures no data loss for a desktop terminal agent.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("services.backup")

# Default backup directory
_BACKUP_DIR = Path("backups")


class BackupService:
    """Automated backup and recovery for Horizon Capital.

    Features:
    - SQLite database file copy (atomic via shutil.copy2)
    - Position snapshot export to JSON
    - Configuration backup
    - Rotating backups (keep last N)
    - Recovery from latest backup
    """

    def __init__(
        self,
        backup_dir: str | Path = _BACKUP_DIR,
        max_backups: int = 10,
    ) -> None:
        self.backup_dir = Path(backup_dir)
        self.max_backups = max_backups
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Database backup
    # ------------------------------------------------------------------

    def backup_database(self, db_path: str | Path) -> str | None:
        """Create a backup of the SQLite database file.

        Uses shutil.copy2 for atomic copy (preserves metadata).

        Returns the backup file path, or None on failure.
        """
        db_path = Path(db_path)
        if not db_path.exists():
            logger.warning("backup_db_not_found", path=str(db_path))
            return None

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"horizon_db_{timestamp}.sqlite"
        backup_path = self.backup_dir / backup_name

        try:
            shutil.copy2(str(db_path), str(backup_path))
            logger.info("database_backed_up", path=str(backup_path))
            self._rotate_backups("horizon_db_*.sqlite")
            return str(backup_path)
        except OSError as exc:
            logger.error("database_backup_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Position snapshot
    # ------------------------------------------------------------------

    def backup_positions(self, positions: list[dict]) -> str | None:
        """Export current positions to a JSON file."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"positions_{timestamp}.json"
        backup_path = self.backup_dir / backup_name

        try:
            snapshot = {
                "timestamp": datetime.now(UTC).isoformat(),
                "positions": positions,
                "count": len(positions),
            }
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, default=str)
            logger.info("positions_backed_up", path=str(backup_path), count=len(positions))
            self._rotate_backups("positions_*.json")
            return str(backup_path)
        except OSError as exc:
            logger.error("positions_backup_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Configuration backup
    # ------------------------------------------------------------------

    def backup_config(self, env_path: str | Path = ".env") -> str | None:
        """Backup the .env configuration file (redacting API keys)."""
        env_path = Path(env_path)
        if not env_path.exists():
            logger.warning("backup_env_not_found", path=str(env_path))
            return None

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"config_{timestamp}.env"
        backup_path = self.backup_dir / backup_name

        try:
            with open(env_path, encoding="utf-8") as f:
                lines = f.readlines()

            # Redact sensitive values
            redacted = []
            sensitive_keys = {"API_KEY", "API_SECRET", "PASSWORD", "TOKEN", "ACCESS_TOKEN"}
            for line in lines:
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    key = stripped.split("=", 1)[0].strip()
                    if any(sk in key.upper() for sk in sensitive_keys):
                        redacted.append(f"{key}=***REDACTED***\n")
                        continue
                redacted.append(line)

            with open(backup_path, "w", encoding="utf-8") as f:
                f.writelines(redacted)

            logger.info("config_backed_up", path=str(backup_path))
            return str(backup_path)
        except OSError as exc:
            logger.error("config_backup_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Full backup
    # ------------------------------------------------------------------

    def full_backup(
        self,
        db_path: str | Path | None = None,
        positions: list[dict] | None = None,
        env_path: str | Path = ".env",
    ) -> dict[str, str | None]:
        """Run a complete backup of all components."""
        results: dict[str, str | None] = {}

        if db_path:
            results["database"] = self.backup_database(db_path)
        if positions is not None:
            results["positions"] = self.backup_positions(positions)
        results["config"] = self.backup_config(env_path)

        logger.info(
            "full_backup_complete",
            components=len([v for v in results.values() if v]),
        )
        return results

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def list_backups(self, pattern: str = "*") -> list[dict]:
        """List available backups sorted by date (newest first)."""
        files = sorted(self.backup_dir.glob(pattern), reverse=True)
        return [
            {
                "filename": f.name,
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "modified": datetime.fromtimestamp(
                    f.stat().st_mtime, tz=UTC
                ).isoformat(),
            }
            for f in files
            if f.is_file()
        ]

    def restore_database(self, backup_path: str | Path, target_path: str | Path) -> bool:
        """Restore a database backup to the target path."""
        backup_path = Path(backup_path)
        target_path = Path(target_path)

        if not backup_path.exists():
            logger.error("restore_backup_not_found", path=str(backup_path))
            return False

        try:
            # Create backup of current db before overwriting
            if target_path.exists():
                emergency = target_path.with_suffix(".pre_restore.sqlite")
                shutil.copy2(str(target_path), str(emergency))

            shutil.copy2(str(backup_path), str(target_path))
            logger.info("database_restored", from_=str(backup_path), to=str(target_path))
            return True
        except OSError as exc:
            logger.error("database_restore_failed", error=str(exc))
            return False

    def load_positions_backup(self, backup_path: str | Path) -> list[dict]:
        """Load positions from a JSON backup file."""
        backup_path = Path(backup_path)
        if not backup_path.exists():
            logger.error("positions_backup_not_found", path=str(backup_path))
            return []

        try:
            with open(backup_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("positions", [])
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("positions_restore_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Rotation
    # ------------------------------------------------------------------

    def _rotate_backups(self, pattern: str) -> None:
        """Delete oldest backups beyond max_backups limit."""
        files = sorted(self.backup_dir.glob(pattern), reverse=True)
        for old_file in files[self.max_backups:]:
            try:
                old_file.unlink()
                logger.debug("backup_rotated", deleted=old_file.name)
            except OSError:
                pass
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D55E0ADF3EBB - verify with scripts/authorship.py verify
