#!/usr/bin/env python3
"""Correct retained end markers in the temporary 6.3.41 transformer."""
from pathlib import Path

path = Path("scripts/apply-6341-offer-catalog-core.py")
text = path.read_text(encoding="utf-8")n
