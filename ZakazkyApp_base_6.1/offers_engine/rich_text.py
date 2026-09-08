"""Shared rich-text helpers for supplier offer descriptions.

Presentation metadata belongs to the offer engine, not to a versioned runtime
layer. This keeps Nevoga Excel/database consumers independent of v769.
"""
from __future__ import annotations

import json
from typing import Any, Iterable


def normalized_segments(raw_segments: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for segment in raw_segments or ():
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text") or "")
        if not text:
            continue
        color = str(segment.get("color") or "").strip()
        changed = bool(segment.get("changed")) or color.upper() in {
            "#FF0000", "FF0000", "#C62828", "C62828",
        }
        current = {
            "text": text,
            "bold": bool(segment.get("bold")),
            "color": "#FF0000" if changed else color,
            "changed": changed,
        }
        if (
            result
            and result[-1]["bold"] == current["bold"]
            and result[-1]["color"] == current["color"]
            and result[-1]["changed"] == current["changed"]
        ):
            result[-1]["text"] += current["text"]
        else:
            result.append(current)
    return result


def decode_segments(raw: Any) -> list[dict[str, Any]]:
    try:
        value = json.loads(str(raw or ""))
    except Exception:
        return []
    return normalized_segments(value if isinstance(value, list) else [])


__all__ = ["decode_segments", "normalized_segments"]
