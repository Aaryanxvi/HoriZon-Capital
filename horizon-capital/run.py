#!/usr/bin/env python3
"""Convenience launcher for Horizon Capital.

Usage:
    python run.py                    # Start terminal agent
    python run.py --headless         # Start without TUI
    python run.py config             # Show configuration
    python run.py version            # Show version

This script sets up the Python path and delegates to the app module.
"""

import os
import sys

# Ensure the backend directory is on the path
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Default to LOCAL storage
os.environ.setdefault("STORAGE_BACKEND", "LOCAL")

from app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
