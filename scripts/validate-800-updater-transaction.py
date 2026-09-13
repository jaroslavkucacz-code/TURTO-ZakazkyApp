#!/usr/bin/env python3
"""Compatibility entry point for the expanded 8.0.8 transaction regressions."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("validate-808-updater.py")), run_name="__main__")
