from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ZakazkyApp_base_6.1"


def replace(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def update_database() -> None:
    path = SRC / "price_lists_domain/platform/database.py"
    replace(
        path,
        """            CREATE TABLE IF NOT EXISTS price_list_ocr_cache(\n""",
        """            CREATE TABLE IF NOT EXISTS catalog_products(\n              id INTEGER PRIMARY KEY AUTOINCREMENT,\n              manufacturer_company_id INTEGER,\n              manufacturer_name TEXT DEFAULT '',\n              internal_code TEXT DEFAULT '',\n              internal_name TEXT DEFAULT '',\n              category_id INTEGER,\n              subgroup_id INTEGER,\n              active INTEGER NOT NULL DEFAULT 1,\n              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n              FOREIGN KEY(manufacturer_company_id) REFERENCES companies(id),\n              FOREIGN KEY(category_id) REFERENCES product_categories(id),\n              FOREIGN KEY(subgroup_id) REFERENCES product_subgroups(id)\n            );\n\n            CREATE TABLE IF NOT EXISTS catalog_product_sources(\n              id INTEGER PRIMARY KEY AUTOINCREMENT,\n              product_id INTEGER NOT NULL,\n              supplier_company_id INTEGER,\n              supplier_name TEXT DEFAULT '',\n              supplier_name_norm TEXT DEFAULT '',\n              source_key TEXT NOT NULL UNIQUE,\n              product_identity TEXT NOT NULL,\n              supplier_product_code TEXT DEFAULT '',\n              source_name TEXT DEFAULT '',\n              source_kind TEXT DEFAULT '',\n              last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n              FOREIGN KEY(product_id) REFERENCES catalog_products(id) ON DELETE CASCADE,\n              FOREIGN KEY(supplier_company_id) REFERENCES companies(id)\n            );\n\n            CREATE TABLE IF NOT EXISTS price_list_ocr_cache(\n""",
    )
    replace(
        path,
        """        _add_column(con, \"price_lists\", \"category_id INTEGER\")\n        _add_column(con, \"price_list_items\", \"category_id INTEGER\")\n        _add_column(con, \"price_list_items\", \"subgroup_id INTEGER REFERENCES product_subgroups(id)\")\n        _add_column(con, \"supplier_offer_items\", \"category_id INTEGER\")\n        _add_column(con, \"supplier_offer_items\", \"subgroup_id INTEGER REFERENCES product_subgroups(id)\")\n        _add_column(con, \"business_document_items\", \"subgroup_id INTEGER REFERENCES product_subgroups(id)\")\n""",
        """        _add_column(con, \"product_categories\", \"default_margin_pct REAL NOT NULL DEFAULT 0\")\n        _add_column(con, \"product_categories\", \"default_discount_pct REAL NOT NULL DEFAULT 0\")\n        _add_column(con, \"product_categories\", \"show_recommended_price INTEGER NOT NULL DEFAULT 1\")\n        _add_column(con, \"product_subgroups\", \"default_margin_pct REAL NOT NULL DEFAULT 0\")\n        _add_column(con, \"product_subgroups\", \"default_discount_pct REAL NOT NULL DEFAULT 0\")\n        _add_column(con, \"price_lists\", \"category_id INTEGER\")\n        _add_column(con, \"price_list_items\", \"category_id INTEGER\")\n        _add_column(con, \"price_list_items\", \"subgroup_id INTEGER REFERENCES product_subgroups(id)\")\n        _add_column(con, \"price_list_items\", \"catalog_product_id INTEGER REFERENCES catalog_products(id)\")\n        _add_column(con, \"supplier_offer_items\", \"category_id INTEGER\")\n        _add_column(con, \"supplier_offer_items\", \"subgroup_id INTEGER REFERENCES product_subgroups(id)\")\n        _add_column(con, \"supplier_offer_items\", \"catalog_product_id INTEGER REFERENCES catalog_products(id)\")\n        _add_column(con, \"business_document_items\", \"subgroup_id INTEGER REFERENCES product_subgroups(id)\")\n        _add_column(con, \"business_document_items\", \"catalog_product_id INTEGER REFERENCES catalog_products(id)\")\n        _add_column(con, \"business_document_items\", \"internal_code_snapshot TEXT DEFAULT ''\")\n        _add_column(con, \"business_document_items\", \"internal_name_snapshot TEXT DEFAULT ''\")\n        _add_column(con, \"business_document_items\", \"purchase_unit_price REAL DEFAULT 0\")\n        _add_column(con, \"business_document_items\", \"margin_pct REAL DEFAULT 0\")\n        _add_column(con, \"business_document_items\", \"recommended_unit_price REAL DEFAULT 0\")\n        _add_column(con, \"business_document_items\", \"show_recommended_price INTEGER DEFAULT 1\")\n""",
    )
    replace(
        path,
        """            CREATE INDEX IF NOT EXISTS idx_product_subgroups_group_order\n              ON product_subgroups(category_id,active,sort_order,name);\n""",
        """            CREATE INDEX IF NOT EXISTS idx_product_subgroups_group_order\n              ON product_subgroups(category_id,active,sort_order,name);\n            CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_products_internal_code\n              ON catalog_products(lower(trim(internal_code))) WHERE trim(coalesce(internal_code,''))<>'';\n            CREATE INDEX IF NOT EXISTS idx_catalog_products_taxonomy\n              ON catalog_products(active,category_id,subgroup_id,manufacturer_name,id);\n            CREATE INDEX IF NOT EXISTS idx_catalog_sources_lookup\n              ON catalog_product_sources(product_identity,supplier_company_id,supplier_name_norm,product_id);\n            CREATE INDEX IF NOT EXISTS idx_catalog_sources_product\n              ON catalog_product_sources(product_id,supplier_name,supplier_product_code);\n""",
    )
    replace(
        path,
        """            CREATE INDEX IF NOT EXISTS idx_price_list_items_subgroup\n              ON price_list_items(subgroup_id,category_id,name,product_code);\n""",
        """            CREATE INDEX IF NOT EXISTS idx_price_list_items_subgroup\n              ON price_list_items(subgroup_id,category_id,name,product_code);\n            CREATE INDEX IF NOT EXISTS idx_price_list_items_catalog_product\n              ON price_list_items(catalog_product_id,price_list_id,active,id);\n""",
    )
    replace(
        path,
        """            CREATE INDEX IF NOT EXISTS idx_supplier_offer_items_taxonomy\n              ON supplier_offer_items(category_id,subgroup_id,offer_id,id);\n""",
        """            CREATE INDEX IF NOT EXISTS idx_supplier_offer_items_taxonomy\n              ON supplier_offer_items(category_id,subgroup_id,offer_id,id);\n            CREATE INDEX IF NOT EXISTS idx_supplier_offer_items_catalog_product\n              ON supplier_offer_items(catalog_product_id,offer_id,id);\n""",
    )


def update_integration() -> None:
    path = SRC / "price_lists_domain/platform/integration.py"
    replace(path, "from . import categories\n", "from . import categories, product_catalog\n")
    replace(path, 'if getattr(storage, "_turto_category_save_v630", False):', 'if getattr(storage, "_turto_catalog_save_v634", False):')
    replace(
        path,
        """    def save(path, parsed, metadata):\n        price_list_id, created = old_save(path, parsed, metadata)\n        category_id = metadata.get(\"category_id\")\n        auto = bool(metadata.get(\"auto_category\", False))\n        with M.db() as con:\n            con.execute(\"UPDATE price_lists SET category_id=? WHERE id=?\", (category_id, price_list_id))\n            if category_id:\n                con.execute(\n                    \"UPDATE price_list_items SET category_id=?,subgroup_id=NULL WHERE price_list_id=?\",\n                    (category_id, price_list_id),\n                )\n        if auto:\n            categories.autocategorize_price_list(M, int(price_list_id), only_empty=True)\n        return price_list_id, created\n""",
        """    def save(path, parsed, metadata):\n        price_list_id, created = old_save(path, parsed, metadata)\n        category_id = metadata.get(\"category_id\")\n        with M.db() as con:\n            con.execute(\"UPDATE price_lists SET category_id=? WHERE id=?\", (category_id, price_list_id))\n            if category_id:\n                con.execute(\n                    \"UPDATE price_list_items SET category_id=?,subgroup_id=NULL WHERE price_list_id=?\",\n                    (category_id, price_list_id),\n                )\n        # Deterministic supplier/product linking replaces keyword guesses.\n        product_catalog.sync_price_list(M, int(price_list_id))\n        return price_list_id, created\n""",
    )
    replace(path, "storage._turto_category_save_v630 = True", "storage._turto_catalog_save_v634 = True")


def update_platform_init() -> None:
    path = SRC / "price_lists_domain/platform/__init__.py"
    replace(
        path,
        "from .integration import install as install_price_integration\n",
        "from .integration import install as install_price_integration\n    from .product_catalog import install as install_product_catalog\n",
    )
    replace(path, 'if getattr(module, "_turto_platform_v6333", False):', 'if getattr(module, "_turto_platform_v6334", False):')
    replace(
        path,
        """    install_price_integration(module)\n    install_offers(module)\n""",
        """    install_price_integration(module)\n    install_product_catalog(module)\n    install_offers(module)\n""",
    )
    replace(path, "module._turto_platform_v6333 = True", "module._turto_platform_v6334 = True")

    domain = SRC / "price_lists_domain/__init__.py"
    replace(domain, "_turto_price_lists_domain_v6333", "_turto_price_lists_domain_v6334", 2)


def update_price_dialogs() -> None:
    path = SRC / "price_lists_domain/platform/price_dialogs.py"
    replace(path, "from . import categories\n", "from . import categories, product_catalog\n")
    replace(path, 'category_value = M.tk.StringVar(value="Automaticky podle položek")', 'category_value = M.tk.StringVar(value="Nezařazeno")')
    replace(
        path,
        'category_labels = ["Automaticky podle položek", "Nezařazeno"] + [row["name"] for row in category_rows]',
        'category_labels = ["Nezařazeno"] + [row["name"] for row in category_rows]',
    )
    replace(
        path,
        'text="Automatika může v jednom ceníku rozdělit jednotlivé položky do různých kategorií.",',
        'text="Zařazení produktů se spravuje ručně v Katalogu produktů a zachová se při dalších aktualizacích ceníku.",',
    )
    replace(
        path,
        """        item_text = \" \".join(str(item.get(key) or \"\") for key in (\"product_code\", \"item_key\", \"name\", \"description\", \"condition_text\"))\n        guessed = categories.classify_text(M, item_text)\n        guessed_subgroup = categories.classify_subgroup_text(M, guessed, item_text)\n""",
        """        guessed = item.get(\"category_id\")\n        guessed_subgroup = item.get(\"subgroup_id\")\n""",
    )
    replace(
        path,
        'category_labels = ["Automaticky podle položek", "Nezařazeno"] + [cat["name"] for cat in categories.list_categories(M)]',
        'category_labels = ["Nezařazeno"] + [cat["name"] for cat in categories.list_categories(M)]',
    )
    replace(
        path,
        'M.ttk.Button(tools, text="Automaticky zařadit nezařazené", command=self.auto_categories).pack(side="left", padx=5)',
        'M.ttk.Button(tools, text="Katalog produktů…", command=lambda: product_catalog.open_product_catalog(M, app)).pack(side="left", padx=5)',
    )


def update_offers() -> None:
    path = SRC / "price_lists_domain/platform/offers.py"
    replace(path, "from . import categories\n", "from . import categories, product_catalog\n")
    replace(
        path,
        'for name, width in (("Produktová skupina", 250), ("Podskupina", 290)):',
        'for name, width in (("Výrobce", 180), ("Interní kód", 130), ("Interní označení", 250), ("Produktová skupina", 250), ("Podskupina", 290)):',
        2,
    )
    replace(
        path,
        """                            \"\"\"SELECT i.id,i.category_id,i.subgroup_id,\n                                      coalesce(c.name,'') category,coalesce(s.name,'') subgroup\n                               FROM supplier_offer_items i\n                               LEFT JOIN product_categories c ON c.id=i.category_id\n                               LEFT JOIN product_subgroups s ON s.id=i.subgroup_id\n                               WHERE i.offer_id=?\"\"\", (self.oid,)\n""",
        """                            \"\"\"SELECT i.id,i.category_id,i.subgroup_id,\n                                      coalesce(c.name,'') category,coalesce(s.name,'') subgroup,\n                                      coalesce(cp.manufacturer_name,'') manufacturer,\n                                      coalesce(cp.internal_code,'') internal_code,\n                                      coalesce(cp.internal_name,'') internal_name\n                               FROM supplier_offer_items i\n                               LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id\n                               LEFT JOIN product_categories c ON c.id=coalesce(cp.category_id,i.category_id)\n                               LEFT JOIN product_subgroups s ON s.id=coalesce(cp.subgroup_id,i.subgroup_id)\n                               WHERE i.offer_id=?\"\"\", (self.oid,)\n""",
    )
    replace(
        path,
        """                            tree.set(iid, \"Produktová skupina\", row[\"category\"] or \"Nezařazeno\")\n                            tree.set(iid, \"Podskupina\", row[\"subgroup\"] or \"\")\n""",
        """                            tree.set(iid, \"Výrobce\", row[\"manufacturer\"] or \"\")\n                            tree.set(iid, \"Interní kód\", row[\"internal_code\"] or \"\")\n                            tree.set(iid, \"Interní označení\", row[\"internal_name\"] or \"\")\n                            tree.set(iid, \"Produktová skupina\", row[\"category\"] or \"Nezařazeno\")\n                            tree.set(iid, \"Podskupina\", row[\"subgroup\"] or \"\")\n""",
    )
    replace(
        path,
        """                _M.ttk.Button(\n                    photo_button.master, text=\"Přiřadit skupinu / podskupinu…\",\n                    command=assign_taxonomy,\n                ).pack(side=\"left\", padx=5)\n""",
        """                _M.ttk.Button(\n                    photo_button.master, text=\"Přiřadit skupinu / podskupinu…\",\n                    command=assign_taxonomy,\n                ).pack(side=\"left\", padx=5)\n                _M.ttk.Button(\n                    photo_button.master, text=\"Katalog produktů…\",\n                    command=lambda: product_catalog.open_product_catalog(_M, self),\n                ).pack(side=\"left\", padx=5)\n""",
    )


def update_price_page() -> None:
    path = SRC / "price_lists_domain/platform/price_page.py"
    replace(path, "from . import categories\n", "from . import categories, product_catalog\n")
    replace(path, 'top, text="Produktové skupiny…", command=lambda: categories.manage_categories(M, app)', 'top, text="Produktové skupiny…", command=lambda: categories.manage_categories(M, app)')
    replace(
        path,
        """    M.ttk.Button(\n        top, text=\"Produktové skupiny…\", command=lambda: categories.manage_categories(M, app)\n    ).pack(side=\"left\", padx=5)\n""",
        """    M.ttk.Button(\n        top, text=\"Produktové skupiny…\", command=lambda: categories.manage_categories(M, app)\n    ).pack(side=\"left\", padx=5)\n    M.ttk.Button(\n        top, text=\"Katalog produktů…\", command=lambda: product_catalog.open_product_catalog(M, app)\n    ).pack(side=\"left\", padx=5)\n""",
    )
    replace(
        path,
        """    current_cols = (\n        \"Produktová skupina\", \"Podskupina\", \"Dodavatel\", \"Větev\", \"Kód\", \"Produkt\", \"Cena/MJ\", \"Zdrojová cena\",\n        \"Cena za\", \"MJ\", \"Přirážka/Sleva\", \"Hmotnost/MJ\", \"Min. odběr\", \"Podmínka\", \"Platí od\", \"Zdrojový ceník\",\n    )\n    current_widths = [250, 280, 180, 180, 120, 340, 115, 115, 75, 65, 115, 105, 95, 230, 95, 240]\n""",
        """    current_cols = (\n        \"Produktová skupina\", \"Podskupina\", \"Interní kód\", \"Interní označení\", \"Výrobce\",\n        \"Dodavatel\", \"Kód dodavatele\", \"Produkt\", \"Nákupní cena/MJ\", \"Marže\",\n        \"Doporučená cena\", \"Sleva\", \"Výsledná cena\", \"MJ\", \"Min. odběr\",\n        \"Podmínka\", \"Platí od\", \"Zdrojový ceník\",\n    )\n    current_widths = [250, 280, 125, 250, 175, 180, 130, 330, 125, 75, 130, 75, 125, 65, 95, 230, 95, 240]\n""",
    )
    replace(
        path,
        """    supplier_expr = \"coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')\"\n    category_expr = \"coalesce(nullif(trim(ic.name),''),nullif(trim(lc.name),''),'Nezařazeno')\"\n    subgroup_expr = \"coalesce(nullif(trim(sg.name),''),'')\"\n""",
        """    if not getattr(app, \"_turto_catalog_price_sync_v634\", False):\n        product_catalog.sync_all_unlinked(M, max_documents=120)\n        app._turto_catalog_price_sync_v634 = True\n    supplier_expr = \"coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')\"\n    category_expr = \"coalesce(nullif(trim(pc.name),''),nullif(trim(ic.name),''),nullif(trim(lc.name),''),'Nezařazeno')\"\n    subgroup_expr = \"coalesce(nullif(trim(psg.name),''),nullif(trim(sg.name),''),'')\"\n""",
    )
    replace(
        path,
        """    join_fts = \" JOIN price_list_items_fts ON price_list_items_fts.rowid=i.id \" if use_fts else \"\"\n    if use_fts:\n        where.append(\"price_list_items_fts MATCH ?\")\n        params.append(_fts_query(query))\n    elif query:\n        where.append(\n            \"lower(coalesce(i.product_code,'')||' '||coalesce(i.item_key,'')||' '||coalesce(i.name,'')||' '||\"\n            \"coalesce(i.description,'')||' '||coalesce(i.condition_text,'')||' '||coalesce(i.gtin,'')||' '||\"\n            \"coalesce(i.customs_code,'')||' '||coalesce(i.dimensions,'')) LIKE ?\"\n        )\n        params.append(\"%\" + query.casefold() + \"%\")\n""",
        """    join_fts = \"\"\n    catalog_search = \"lower(coalesce(cp.internal_code,'')||' '||coalesce(cp.internal_name,'')||' '||coalesce(cp.manufacturer_name,''))\"\n    if use_fts:\n        where.append(\"(i.id IN (SELECT rowid FROM price_list_items_fts WHERE price_list_items_fts MATCH ?) OR \" + catalog_search + \" LIKE ?)\")\n        params.extend([_fts_query(query), \"%\" + query.casefold() + \"%\"])\n    elif query:\n        where.append(\n            \"lower(coalesce(i.product_code,'')||' '||coalesce(i.item_key,'')||' '||coalesce(i.name,'')||' '||\"\n            \"coalesce(i.description,'')||' '||coalesce(i.condition_text,'')||' '||coalesce(i.gtin,'')||' '||\"\n            \"coalesce(i.customs_code,'')||' '||coalesce(i.dimensions,'')||' '||coalesce(cp.internal_code,'')||' '||\"\n            \"coalesce(cp.internal_name,'')||' '||coalesce(cp.manufacturer_name,'')) LIKE ?\"\n        )\n        params.append(\"%\" + query.casefold() + \"%\")\n""",
    )
    replace(path, 'where.append("coalesce(i.category_id,p.category_id)=?")', 'where.append("coalesce(cp.category_id,i.category_id,p.category_id)=?")')
    replace(path, 'where.append("i.subgroup_id=?")', 'where.append("coalesce(cp.subgroup_id,i.subgroup_id)=?")')
    replace(
        path,
        """                 i.condition_text,p.title,p.valid_from,p.valid_to,p.product_group,p.branch,\n                 {supplier_expr} supplier,{category_expr} category,{subgroup_expr} subgroup,\n""",
        """                 i.condition_text,p.title,p.valid_from,p.valid_to,p.product_group,p.branch,\n                 {supplier_expr} supplier,{category_expr} category,{subgroup_expr} subgroup,\n                 cp.id catalog_product_id,coalesce(cp.internal_code,'') internal_code,\n                 coalesce(cp.internal_name,'') internal_name,\n                 coalesce(nullif(trim(cp.manufacturer_name),''),{supplier_expr}) manufacturer,\n                 coalesce(psg.default_margin_pct,pc.default_margin_pct,0) margin_pct,\n                 coalesce(psg.default_discount_pct,pc.default_discount_pct,0) sales_discount_pct,\n                 coalesce(pc.show_recommended_price,1) show_recommended_price,\n""",
    )
    replace(
        path,
        """          LEFT JOIN companies c ON c.id=p.supplier_company_id\n          LEFT JOIN product_categories ic ON ic.id=i.category_id\n          LEFT JOIN product_categories lc ON lc.id=p.category_id\n          LEFT JOIN product_subgroups sg ON sg.id=i.subgroup_id\n""",
        """          LEFT JOIN companies c ON c.id=p.supplier_company_id\n          LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id\n          LEFT JOIN product_categories pc ON pc.id=cp.category_id\n          LEFT JOIN product_subgroups psg ON psg.id=cp.subgroup_id\n          LEFT JOIN product_categories ic ON ic.id=i.category_id\n          LEFT JOIN product_categories lc ON lc.id=p.category_id\n          LEFT JOIN product_subgroups sg ON sg.id=i.subgroup_id\n""",
    )
    replace(
        path,
        """        app.price_current_rows[iid] = {\"price_list_id\": int(row[\"price_list_id\"]), \"item_id\": int(row[\"item_id\"])}\n        tree.insert(\n            \"\", \"end\", iid=iid,\n            values=(\n                row[\"category\"], row[\"subgroup\"] or \"\", row[\"supplier\"], row[\"branch\"] or \"\", row[\"product_code\"] or row[\"item_key\"] or \"\",\n                row[\"name\"] or row[\"description\"] or \"\", _format_price(row[\"normalized_unit_price\"], row[\"currency\"]),\n                _format_price(row[\"source_price\"], row[\"currency\"]), f\"{float(row['price_basis_qty'] or 1):g}\",\n                row[\"unit\"] or \"\", _format_adjustment(row),\n                f\"{float(row['weight_unit'] or 0):g} kg\" if row[\"weight_unit\"] else \"\",\n                f\"{float(row['minimum_qty'] or 0):g}\" if row[\"minimum_qty\"] else \"\",\n                row[\"condition_text\"] or \"\", M.fmt_date(row[\"valid_from\"]), row[\"title\"] or \"\",\n            ),\n        )\n""",
        """        app.price_current_rows[iid] = {\n            \"price_list_id\": int(row[\"price_list_id\"]), \"item_id\": int(row[\"item_id\"]),\n            \"catalog_product_id\": int(row[\"catalog_product_id\"]) if row[\"catalog_product_id\"] else None,\n        }\n        recommended, final = product_catalog.calculate_prices(\n            row[\"normalized_unit_price\"], row[\"margin_pct\"], row[\"sales_discount_pct\"]\n        )\n        tree.insert(\n            \"\", \"end\", iid=iid,\n            values=(\n                row[\"category\"], row[\"subgroup\"] or \"\", row[\"internal_code\"], row[\"internal_name\"],\n                row[\"manufacturer\"], row[\"supplier\"], row[\"product_code\"] or row[\"item_key\"] or \"\",\n                row[\"name\"] or row[\"description\"] or \"\", _format_price(row[\"normalized_unit_price\"], row[\"currency\"]),\n                f\"{float(row['margin_pct'] or 0):g} %\",\n                _format_price(recommended, row[\"currency\"]) if row[\"show_recommended_price\"] else \"—\",\n                f\"{float(row['sales_discount_pct'] or 0):g} %\", _format_price(final, row[\"currency\"]),\n                row[\"unit\"] or \"\", f\"{float(row['minimum_qty'] or 0):g}\" if row[\"minimum_qty\"] else \"\",\n                row[\"condition_text\"] or \"\", M.fmt_date(row[\"valid_from\"]), row[\"title\"] or \"\",\n            ),\n        )\n""",
    )


def update_release() -> None:
    (ROOT / "release_version.txt").write_text("6.3.34\n", encoding="utf-8")
    (ROOT / "release_notes.txt").write_text(
        """• Klíčová slova byla odstraněna z uživatelského rozhraní a produktové zařazení se už automaticky nehádá. Skupiny a podskupiny se spravují ručně.\n"
        "• Přidán stabilní Katalog produktů. U produktu je vidět výrobce, zdrojový dodavatel, dodavatelský kód, označení ve zdroji, interní kód, interní označení, skupina, podskupina a počet cenových zdrojů.\n"
        "• Produkty lze hromadně přesouvat mezi skupinami a podskupinami. Stejný produkt v novém ceníku převezme zařazení, interní kód i interní označení podle dodavatele a produktového kódu.\n"
        "• U každé podskupiny lze nastavit základní marži a základní slevu. Skupina obsahuje stejné výchozí hodnoty pro produkty bez podskupiny.\n"
        "• U každé hlavní skupiny lze zvolit, zda se má ve vydaných nabídkách zobrazovat doporučená i výsledná cena, nebo pouze výsledná cena.\n"
        "• Aktuální ceny nově ukazují interní kód a označení, výrobce, nákupní cenu, marži, doporučenou cenu, slevu a výslednou cenu. Doporučená cena se u skupin s režimem „Pouze výsledná“ nezobrazuje.\n"
        "• Výpočet je jednotný: doporučená cena = nákupní cena × (1 + marže/100); výsledná cena = doporučená cena × (1 − sleva/100).\n"
        "• Datový základ budoucích Vydaných nabídek a objednávek obsahuje vazbu na katalog produktu a snímky interního označení, nákupní ceny, marže a doporučené ceny.\n"
        "• Databázová změna je pouze aditivní. Historické nabídky, ceníky, ceny, fyzické archivy, Outlook import a uživatelská data zůstávají zachovány.\n""",
        encoding="utf-8",
    )


def write_validation() -> None:
    path = ROOT / "scripts/validate-6334-product-catalog.py"
    path.write_text(r'''from __future__ import annotations
import sqlite3
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
for rel, needles in {
    "price_lists_domain/platform/database.py": (
        "CREATE TABLE IF NOT EXISTS catalog_products", "CREATE TABLE IF NOT EXISTS catalog_product_sources",
        "default_margin_pct", "show_recommended_price", "catalog_product_id INTEGER REFERENCES catalog_products",
    ),
    "price_lists_domain/platform/categories.py": (
        "Product placement is intentionally not guessed from keywords", "Produkty ve výběru…",
        "Základní marže [%]", "Pouze výsledná",
    ),
    "price_lists_domain/platform/product_catalog.py": (
        "def sync_price_list", "def sync_supplier_offer", "def update_product",
        "def calculate_prices", "Interní kód", "Zdroje a ceny…",
    ),
    "price_lists_domain/platform/price_page.py": (
        "Interní kód", "Nákupní cena/MJ", "Doporučená cena", "Výsledná cena",
        "product_catalog.calculate_prices",
    ),
}.items():
    text = (root / rel).read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text, (rel, needle)

categories_text = (root / "price_lists_domain/platform/categories.py").read_text(encoding="utf-8")
assert "Klíčová slova" not in categories_text
assert "def classify_text(M, value: object):\n    return None" in categories_text

sys.path.insert(0, str(root))
from price_lists_domain.platform import database, product_catalog

class M:
    sqlite3 = sqlite3
    PRICE_FTS_AVAILABLE = False
    def __init__(self, path): self.path = path
    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.create_collation("CZECH", lambda a,b: (str(a)>str(b))-(str(a)<str(b)))
        con.execute("PRAGMA foreign_keys=ON")
        return con

with tempfile.TemporaryDirectory() as tmp:
    m = M(Path(tmp) / "test.db")
    with m.db() as con:
        con.executescript("""
        CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE companies(id INTEGER PRIMARY KEY,official_name TEXT,short_name TEXT,active INTEGER DEFAULT 1);
        CREATE TABLE product_categories(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE COLLATE CZECH,parent_id INTEGER,keywords TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 100,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE product_subgroups(id INTEGER PRIMARY KEY AUTOINCREMENT,category_id INTEGER NOT NULL,name TEXT NOT NULL,keywords TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 100,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(category_id,name));
        CREATE TABLE projects(id INTEGER PRIMARY KEY,active INTEGER DEFAULT 1,end_date TEXT);
        CREATE TABLE price_lists(id INTEGER PRIMARY KEY,supplier_company_id INTEGER,supplier_name TEXT,category_id INTEGER,archived INTEGER DEFAULT 0,valid_from TEXT,valid_to TEXT,parse_status TEXT,title TEXT,product_group TEXT,branch TEXT,source_filename TEXT,imported_at TEXT);
        CREATE TABLE price_list_items(id INTEGER PRIMARY KEY,price_list_id INTEGER,category_id INTEGER,subgroup_id INTEGER,active INTEGER DEFAULT 1,product_code TEXT,supplier_item_code TEXT,item_key TEXT,name TEXT,description TEXT,condition_text TEXT,normalized_unit_price REAL,currency TEXT);
        CREATE TABLE supplier_offers(id INTEGER PRIMARY KEY,supplier_company_id INTEGER,supplier_name TEXT,archived INTEGER DEFAULT 0,offer_date TEXT,currency TEXT,offer_number TEXT,reference TEXT);
        CREATE TABLE supplier_offer_items(id INTEGER PRIMARY KEY,offer_id INTEGER,category_id INTEGER,subgroup_id INTEGER,product_code TEXT,item_key TEXT,original_name TEXT,details TEXT,unit_price REAL);
        CREATE TABLE actions(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,status TEXT,created_date TEXT,deadline TEXT,updated_at TEXT,project_id INTEGER);
        CREATE TABLE tasks(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,done INTEGER DEFAULT 0,due_date TEXT,done_at TEXT);
        CREATE TABLE requests(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,no_response INTEGER DEFAULT 0,received_date TEXT,asked_date TEXT);
        INSERT INTO companies(id,official_name,active) VALUES(1,'Výrobce A',1);
        INSERT INTO price_lists(id,supplier_company_id,supplier_name,valid_from,valid_to,title) VALUES(1,1,'Výrobce A','2026-01-01','','Ceník A');
        INSERT INTO price_list_items(id,price_list_id,product_code,item_key,name,normalized_unit_price,currency) VALUES(1,1,'ABC-1','ABC-1','Produkt A',100,'CZK');
        INSERT INTO supplier_offers(id,supplier_company_id,supplier_name,offer_date,currency) VALUES(1,1,'Výrobce A','2026-02-01','CZK');
        INSERT INTO supplier_offer_items(id,offer_id,product_code,item_key,original_name,unit_price) VALUES(1,1,'ABC-1','ABC-1','Produkt A',95);
        """)
    database.ensure_platform_schema(m)
    assert product_catalog.sync_price_list(m, 1) == 1
    assert product_catalog.sync_supplier_offer(m, 1) == 1
    with m.db() as con:
        products = con.execute("SELECT * FROM catalog_products").fetchall()
        assert len(products) == 1
        product_id = int(products[0]["id"])
        linked = con.execute("SELECT catalog_product_id FROM price_list_items WHERE id=1").fetchone()[0]
        linked_offer = con.execute("SELECT catalog_product_id FROM supplier_offer_items WHERE id=1").fetchone()[0]
        assert linked == product_id == linked_offer
        group = con.execute("SELECT id FROM product_categories WHERE name='AKUSTICKÁ IZOLACE SCHODIŠŤ'").fetchone()[0]
        subgroup = con.execute("SELECT id FROM product_subgroups WHERE category_id=? ORDER BY id LIMIT 1", (group,)).fetchone()[0]
        con.execute("UPDATE product_subgroups SET default_margin_pct=25,default_discount_pct=10 WHERE id=?", (subgroup,))
    product_catalog.update_product(m, product_id, manufacturer_name="Výrobce A", internal_code="T-001", internal_name="Interní produkt A", category_id=group, subgroup_id=subgroup)
    defaults = product_catalog.quote_defaults(m, product_id, 100)
    assert round(defaults["recommended_unit_price"], 4) == 125
    assert round(defaults["final_unit_price"], 4) == 112.5
    with m.db() as con:
        row = con.execute("SELECT category_id,subgroup_id FROM price_list_items WHERE id=1").fetchone()
        assert row[0] == group and row[1] == subgroup
        assert con.execute("SELECT internal_code FROM catalog_products WHERE id=?", (product_id,)).fetchone()[0] == "T-001"
        cols = {row[1] for row in con.execute("PRAGMA table_info(business_document_items)")}
        for col in ("catalog_product_id", "internal_code_snapshot", "purchase_unit_price", "margin_pct", "recommended_unit_price", "show_recommended_price"):
            assert col in cols

print("6.3.34 product catalogue and pricing regression checks passed")
''', encoding="utf-8")


def update_publish_script() -> None:
    path = ROOT / "scripts/publish-update.sh"
    replace(
        path,
        'grep -q "def choose_taxonomy" "$DIR/_runtime/price_lists_domain/platform/categories.py"\n',
        'grep -q "def choose_taxonomy" "$DIR/_runtime/price_lists_domain/platform/categories.py"\n'
        'grep -q "CREATE TABLE IF NOT EXISTS catalog_products" "$DIR/_runtime/price_lists_domain/platform/database.py"\n'
        'grep -q "def sync_price_list" "$DIR/_runtime/price_lists_domain/platform/product_catalog.py"\n'
        'grep -q "Doporučená cena" "$DIR/_runtime/price_lists_domain/platform/price_page.py"\n'
        'grep -q "Produkty ve výběru" "$DIR/_runtime/price_lists_domain/platform/categories.py"\n',
    )


update_database()
update_integration()
update_platform_init()
update_price_dialogs()
update_offers()
update_price_page()
update_release()
write_validation()
update_publish_script()
print("TURTO CRM 6.3.34 source patch complete")
