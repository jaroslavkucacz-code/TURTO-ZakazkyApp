#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.9.4 release pipeline hardening."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile


def run_guard(script: pathlib.Path, target: str, current: str | None):
    with tempfile.TemporaryDirectory(prefix="turto_release_guard_") as td:
        root = pathlib.Path(td)
        (root / "release_version.txt").write_text(target + "\n", encoding="utf-8")
        if current is not None:
            (root / "latest.json").write_text(
                json.dumps({"version": current, "file": "dummy.zip"}) + "\n",
                encoding="utf-8",
            )
        return subprocess.run(
            [sys.executable, str(script)],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )


def main() -> None:
    repo = pathlib.Path(__file__).resolve().parents[1]
    guard = repo / "scripts" / "validate-release-version.py"
    workflow = repo / ".github" / "workflows" / "publish-update.yml"

    ok = run_guard(guard, "7.9.4", "7.9.3")
    assert ok.returncode == 0, ok.stderr or ok.stdout
    assert "7.9.3 -> 7.9.4" in ok.stdout

    same = run_guard(guard, "7.9.3", "7.9.3")
    assert same.returncode != 0
    assert "Publikace zastavena" in (same.stderr + same.stdout)

    lower = run_guard(guard, "7.9.2", "7.9.3")
    assert lower.returncode != 0

    first = run_guard(guard, "1.0.0", None)
    assert first.returncode == 0
    assert "První vydání" in first.stdout

    invalid = run_guard(guard, "7.9.beta", "7.9.3")
    assert invalid.returncode != 0
    assert "Neplatný formát verze" in (invalid.stderr + invalid.stdout)

    # Source validation and the packaged runtime must execute the same active
    # post-baseline layer.  The release packager intentionally copies the root
    # file into the staged application, so a drift here would make CI validate a
    # different runtime than customers receive.
    packaged_owner = repo / "post_baseline.py"
    source_owner = repo / "ZakazkyApp_base_6.1" / "post_baseline.py"
    assert packaged_owner.read_bytes() == source_owner.read_bytes(), (
        "post_baseline.py drift: source tests and packaged runtime differ"
    )

    text = workflow.read_text(encoding="utf-8")
    required = (
        "Validate release version advances",
        "python scripts/validate-release-version.py",
        "python scripts/validate-793-ui-cleanup.py ZakazkyApp_base_6.1",
        "python scripts/validate-794-ui-optimization.py ZakazkyApp_base_6.1",
        "python scripts/validate-794-startup-optimization.py ZakazkyApp_base_6.1",
        "ZakazkyApp_base_6.1/price_lists_domain/platform/**",
        "ZakazkyApp_base_6.1/runtime_bootstrap.py",
        "ZakazkyApp_base_6.1/post_baseline.py",
    )
    for token in required:
        assert token in text, token

    print("TURTO CRM 7.9.4 release pipeline: OK")


if __name__ == "__main__":
    main()
