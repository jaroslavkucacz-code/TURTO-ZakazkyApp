#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.2 visual issued offers and column widths."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
REPOSITORY = ROOT.parent
sys.path.insert(0, str(ROOT))

from price_lists_domain.issued_offers import service  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class Module:
    def __init__(self, path: Path):
        self.path = path

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def get_setting(_key, default=""):
        return default

    @staticmethod
    def set_setting(_key, _value):
        return None


def numbering_check() -> None:
    with tempfile.TemporaryDirectory(prefix="turto7200_number_") as temp:
        module = Module(Path(temp) / "numbering.db")
        with module.db() as con:
            con.executescript(
                """
                CREATE TABLE document_sequences(
                  document_type TEXT NOT NULL,
                  calendar_year INTEGER NOT NULL,
                  last_number INTEGER NOT NULL DEFAULT 0,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY(document_type,calendar_year)
                );
                CREATE TABLE business_documents(
                  id INTEGER PRIMARY KEY,
                  document_type TEXT,
                  document_number TEXT,
                  issue_date TEXT
                );
                INSERT INTO business_documents
                  (id,document_type,document_number,issue_date)
                VALUES
                  (1,'issued_offer','CN-2026-0042','2026-01-10'),
                  (2,'issued_offer','CN26-00043','2026-02-10');
                """
            )
        first = service.preview_document_number(module, "2026-09-01")
        second = service.preview_document_number(module, "2026-09-01")
        assert first == second == "CN26-00044", (first, second)
        with module.db() as con:
            assert con.execute(
                "SELECT COUNT(*) FROM document_sequences"
            ).fetchone()[0] == 0
            consumed = service._sequence_number(con, module, "2026-09-01")
        assert consumed == first
        assert service.preview_document_number(module, "2026-09-01") == "CN26-00045"


def main() -> None:
    layer = read(ROOT / "v710_cleanup.py")
    visual = read(ROOT / "v720_visual_offer.py")
    legacy = read(ROOT / "v638_table_updatefix.py")
    baseline = read(REPOSITORY / "post_baseline.py")
    launcher = read(ROOT / "ZakazkyCRM.pyw")
    settings = read(ROOT / "price_lists_domain" / "issued_offers" / "settings.py")
    service_source = read(ROOT / "price_lists_domain" / "issued_offers" / "service.py")
    publish = read(REPOSITORY / "scripts" / "publish-update.sh")
    real_ui = read(REPOSITORY / "scripts" / "validate-real-ui.py")

    assert "t.unbind(seq)" not in legacy
    assert "'<ButtonRelease-1>'" not in legacy
    assert "_turto_v720_width_owner" in baseline
    reclaim = baseline.split("def reclaim_tree_layout", 1)[1].split(
        "# ------------------------------------------------------------------", 1
    )[0]
    assert "redraw_only" in reclaim
    assert "widget.unbind('<Configure>')" in reclaim
    assert "_v720_resize_active" in layer
    assert "Šířka vybraného sloupce [px]" in layer
    assert "Použít šířku" in layer
    assert "30 až 2 000 px" in layer

    assert "class OfferPreview" in visual
    assert "class InternalItemPanel" in visual
    assert "pdf_renderer.render_offer_pdf" in visual
    assert "service.record_revision = lambda" in visual
    assert "Dvojklikem upravíte" in visual
    assert "Cena položky" in visual
    assert "Interní cenové údaje" in visual
    assert "_turto_v720_width_owner = True" in visual

    assert 'CN{int(year) % 100:02d}-{int(sequence):05d}' in service_source
    assert "def preview_document_number" in service_source
    assert "issued_offer_number_prefix" not in settings
    assert "issued_offer_number_width" not in settings
    assert "Číslování je pevné: CNrr-00000" in settings

    assert "import v720_visual_offer" in launcher or ",v720_visual_offer" in launcher
    assert "v710_cleanup.apply(app);v720_visual_offer.apply(app)" in launcher
    assert "v720_visual_offer.py" in publish
    assert "validate-7200-visual-issued-offers.py" in publish
    assert "v720_visual_offer.apply(app)" in real_ui
    assert "Vizuální editor nevykreslil produkční PDF" in real_ui

    version = read(REPOSITORY / "release_version.txt").strip()
    assert version == "7.2.0", version
    numbering_check()
    print("OK 7.2.0: persistent widths, fixed numbering and exact visual PDF editor")


if __name__ == "__main__":
    main()
