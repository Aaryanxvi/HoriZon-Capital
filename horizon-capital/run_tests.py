#!/usr/bin/env python3
"""Run the Horizon Capital test suite.

Usage:
    python run_tests.py              # Run all smoke tests
    python run_tests.py -v           # Verbose output
    python run_tests.py -k "VaR"     # Run only VaR tests
"""

import os
import sys
import subprocess

# Setup paths
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"
os.environ["APP_DEBUG"] = "false"

# Run pytest
args = [sys.executable, "-m", "pytest", "tests/test_smoke.py", "-v", "--tb=short"]
args.extend(sys.argv[1:])

sys.exit(subprocess.call(args, cwd=backend_dir))
