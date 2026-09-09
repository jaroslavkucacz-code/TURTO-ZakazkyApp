#!/usr/bin/env python3
"""Refuse accidental TURTO CRM republishing under an already released version."""
from __future__ import annotations

import json
import re
from pathlib import Path

VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")


def parse_version(value: str) -> tuple[int, ...]:
    text = str(value or "").strip()
    if not VERSION_RE.fullmatch(text):
        raise SystemExit(f"Neplatný formát verze: {text!r}")
    return tuple(int(part) for part in text.split("."))


def normalized(parts: tuple[int, ...], width: int = 4) -> tuple[int, ...]:
    return parts + (0,) * max(0, width - len(parts))


def main() -> None:
    target_text = Path("release_version.txt").read_text(encoding="utf-8").strip()
    target = normalized(parse_version(target_text))

    manifest = Path("latest.json")
    if not manifest.exists():
        print(f"První vydání: {target_text}")
        return

    data = json.loads(manifest.read_text(encoding="utf-8"))
    current_text = str(data.get("version") or "").strip()
    current = normalized(parse_version(current_text))
    if target <= current:
        raise SystemExit(
            "Publikace zastavena: release_version.txt musí být vyšší než "
            f"aktuální vydaná verze ({target_text} <= {current_text})."
        )

    print(f"Posun verze ověřen: {current_text} -> {target_text}")


if __name__ == "__main__":
    main()
