#!/usr/bin/env python3
"""Guard retired TURTO CRM 8.0.4 legacy refresh overlaps."""
from pathlib import Path
import sys


def main() -> None:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()

    v605 = (base / "crm_v605.py").read_text(encoding="utf-8")
    assert "def _patch_mivo" not in v605
    assert "def _patch_sort_reset" not in v605
    assert "def _patch_late_font" not in v605
    assert "def _ensure" not in v605
    assert "CREATE TABLE IF NOT EXISTS recipient_usage" not in v605
    assert "tag_configure" not in v605
    assert "after_idle" not in v605
    assert "M.App" not in v605
    assert "_turto_v605_retired_804" in v605

    v608 = (base / "v608_stability.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS recipient_usage" in v608

    v628 = (base / "v628_modernui_resize.py").read_text(encoding="utf-8")
    assert "tree.tag_configure('status_late', font=('Calibri',10,'bold'))" in v628
    assert "single owner of both status_late colors and its font" in v628

    v632 = (base / "v632_offerlinks.py").read_text(encoding="utf-8")
    assert "for name in ('refresh_requests','refresh_all'):" in v632
    assert "for name in ('refresh_actions','refresh_requests','refresh_all'):" not in v632
    assert "Keep only the Request-side count here" in v632

    v637 = (base / "v637_project_offer_model.py").read_text(encoding="utf-8")
    assert "setattr(M.App,name,make(old,name!='refresh_actions'))" in v637
    assert "for ms in (0,20,120,350)" not in v637
    assert "_style_urgent_requests" not in v637
    assert "_install_cleanup_events" not in v637
    assert "_v633_deadline_labels" not in v637

    worksets = (base / "price_lists_domain" / "platform" / "worksets.py").read_text(encoding="utf-8")
    assert 'URGENT_REQUEST_TAG = "deadline_urgent"' in worksets
    assert "urgent = _request_is_urgent(row, today)" in worksets

    print("TURTO CRM 8.0.4 legacy overlap cleanup: OK")


if __name__ == "__main__":
    main()
