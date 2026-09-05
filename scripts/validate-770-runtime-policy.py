#!/usr/bin/env python3
"""Contract test for TURTO CRM 7.7 final runtime policy and rollback."""
from __future__ import annotations

import ast
import pathlib
import sys


def main():
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    repository = source.parent
    policy_path = source / "v770_runtime_policy.py"
    bootstrap_path = source / "runtime_bootstrap.py"
    updater_path = source / "crm_updater.pyw"
    launcher_path = source / "ZakazkyCRM.pyw"
    for path in (policy_path, bootstrap_path, updater_path, launcher_path):
        assert path.is_file(), path
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    policy = policy_path.read_text(encoding="utf-8")
    assert 'M.APP_NAME = "TURTO CRM"' in policy
    assert 'app.title("TURTO CRM")' in policy
    assert "turto_crm.ico" in policy and "turto_crm.png" in policy
    assert "_refresh_action_deadline_highlights = _attention_callback" in policy
    assert "_refresh_request_date_highlights = _request_attention_callback" in policy
    assert "_fit_action_tree" in policy and "_sync_filter_bar" in policy
    assert "_workarea_for_window" in policy and "MonitorFromWindow" in policy
    assert "_workarea_for_point" in policy and "MonitorFromPoint" in policy
    assert "_reposition_popup" in policy
    assert "_ensure_offer_plexus_images" in policy
    assert "offer_source_attachments" in policy and "source_pdf" in policy
    assert "offer_image_assets" in policy and "nevoga:plexus:" in policy
    assert "Obnovení předchozí verze" in policy
    assert "rollback_preserves_database" in policy

    bootstrap = bootstrap_path.read_text(encoding="utf-8")
    assert bootstrap.count('"v770_runtime_policy"') >= 1
    assert bootstrap.index('"v7616_requests_plexus_assets"') < bootstrap.index('"v770_runtime_policy"')
    launcher = launcher_path.read_text(encoding="utf-8")
    assert "runtime_bootstrap.apply_all(app)" in launcher
    assert ".apply(app)" not in launcher

    updater = updater_path.read_text(encoding="utf-8")
    for token in ("_database_backup", "_snapshot_program", "latest.json", "--install", "rollback"):
        assert token in updater, token
    assert "src.backup(dst)" in updater
    assert '"_rollback"' in updater

    assert "def _ensure_icon_assets" in policy
    assert 'Image.new("RGBA"' in policy
    assert 'image.save(\n            ico' in policy or 'format="ICO"' in policy
    assert 'gold = (214, 169, 0, 255)' in policy

    version = (repository / "release_version.txt").read_text(encoding="utf-8").strip()
    assert version == "7.7.0", version
    publish = (repository / "scripts" / "publish-update.sh").read_text(encoding="utf-8")
    assert "validate-770-runtime-policy.py" in publish
    assert "rollback_manifest.json" in publish
    assert "ZakazkyApp_v7.6.16.zip" in publish
    print("OK 7.7: identity, PLEXUS assets, deadlines, monitor policy and reversible updater")


if __name__ == "__main__":
    main()
