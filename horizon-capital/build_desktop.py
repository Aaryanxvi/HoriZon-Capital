# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-8F3228CB4974
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Build script for Horizon Capital desktop app.

Steps:
  1. Build React frontend  → frontend/dist/
  2. Bundle Python backend  → backend-dist/desktop_entry/
  3. Package with Electron  → desktop/dist/ (installer)

Usage:
  python build_desktop.py          # Full build
  python build_desktop.py --skip-frontend   # Skip frontend build
  python build_desktop.py --skip-backend    # Skip backend bundle
  python build_desktop.py --skip-electron   # Skip electron packaging
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
FRONTEND_DIR = ROOT / "frontend"
BACKEND_DIR = ROOT / "backend"
DESKTOP_DIR = ROOT / "desktop"
BACKEND_DIST = ROOT / "backend-dist"


def run(cmd: list[str], cwd: Path, label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  > {' '.join(cmd)}")
    print(f"{'='*60}\n")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"\nERROR: {label} failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def build_frontend() -> None:
    """Build React SPA with Vite."""
    run(["npm", "run", "build"], cwd=FRONTEND_DIR, label="Building frontend (Vite)")
    dist = FRONTEND_DIR / "dist"
    if not dist.is_dir():
        print("ERROR: frontend/dist not found after build")
        sys.exit(1)
    print(f"  Frontend built → {dist}")


def build_backend() -> None:
    """Bundle Python backend with PyInstaller."""
    entry = BACKEND_DIR / "desktop_entry.py"
    if not entry.exists():
        print(f"ERROR: {entry} not found")
        sys.exit(1)

    # Clean previous build
    if BACKEND_DIST.exists():
        shutil.rmtree(BACKEND_DIST)

    run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--name", "desktop_entry",
            "--distpath", str(BACKEND_DIST),
            "--add-data", f"{BACKEND_DIR / 'app'};app",
            str(entry),
        ],
        cwd=BACKEND_DIR,
        label="Bundling backend (PyInstaller)",
    )

    out = BACKEND_DIST / "desktop_entry"
    if not out.is_dir():
        print(f"ERROR: {out} not found after PyInstaller")
        sys.exit(1)
    print(f"  Backend bundled → {out}")


def build_electron() -> None:
    """Install deps and package with electron-builder."""
    run(["npm", "install"], cwd=DESKTOP_DIR, label="Installing Electron dependencies")
    run(["npm", "run", "dist"], cwd=DESKTOP_DIR, label="Packaging desktop app (electron-builder)")

    dist = DESKTOP_DIR / "dist"
    print(f"\n  Desktop app packaged → {dist}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Horizon Capital desktop app")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--skip-electron", action="store_true")
    args = parser.parse_args()

    print("Horizon Capital Desktop Build")
    print(f"  Root: {ROOT}")

    if not args.skip_frontend:
        build_frontend()
    else:
        print("  Skipping frontend build")

    if not args.skip_backend:
        build_backend()
    else:
        print("  Skipping backend bundle")

    if not args.skip_electron:
        build_electron()
    else:
        print("  Skipping electron packaging")

    print("\n" + "="*60)
    print("  BUILD COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 8F3228CB4974 - verify with scripts/authorship.py verify
