
import os, sys, sqlite3, shutil, subprocess
from pathlib import Path
from datetime import datetime, date

APP_NAME = "ZakázkyApp"
APP_VERSION = "5.0.2"

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
LOGO = ROOT / "turto_logo.png"

def stable_root():
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    else:
        base = Path.home() / "Documents"
    return base / "TURTO Zakazky"

DATA_ROOT = stable_root()
DATA_DIR = DATA_ROOT / "data"
BACKUP_DIR = DATA_ROOT / "backup"
DB_PATH = DATA_DIR / "zakazky.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def bootstrap_db():
    if DB_PATH.exists():
        return
    for source in [ROOT/"data"/"zakazky.db", ROOT/"seed"/"zakazky.db"]:
        if source.exists():
            shutil.copy2(source, DB_PATH)
            return

def ensure_schema():
    bootstrap_db()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS app_meta(
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )""")
        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('schema_version','5.0')")
        con.commit()

def run_legacy():
    legacy = ROOT / "app_legacy_v4.py"
    if not legacy.exists():
        raise RuntimeError("Chybí fallback app_legacy_v4.py")
    subprocess.run([sys.executable, str(legacy)], check=False)

try:
    from PySide6.QtCore import Qt, QSize, QSortFilterProxyModel
    from PySide6.QtGui import QAction, QFont, QIcon, QColor, QStandardItemModel, QStandardItem
    from PySide6.QtWidgets import (
        QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,
        QLineEdit,QComboBox,QTableView,QFrame,QStackedWidget,QSplitter,QDialog,QDialogButtonBox,
        QFormLayout,QTextEdit,QTabWidget,QToolButton,QMessageBox,QHeaderView,QAbstractItemView
    )
except Exception:
    if __name__ == "__main__":
        run_legacy()
        sys.exit(0)

GOLD = "#f2b90b"
GOLD2 = "#ffd23b"
BG = "#0d1318"
PANEL = "#141a20"
PANEL2 = "#1a2127"
FIELD = "#20272d"
BORDER = "#343c43"
TEXT = "#f3f4f5"
MUTED = "#a8b0b7"
GREEN = "#4fb579"
RED = "#d86561"

QSS = f"""
* {{
    font-family: Calibri;
    font-size: 11pt;
    color: {TEXT};
}}
QMainWindow, QWidget {{
    background: {BG};
}}
QFrame#TopBar, QFrame#NavBar {{
    background: #11171c;
    border: none;
}}
QFrame#Panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#Title {{
    font-size: 20pt;
    font-weight: 700;
}}
QLabel#Muted {{
    color: {MUTED};
}}
QLabel#TestBanner {{
    background: {GOLD};
    color: #111;
    font-weight: 800;
    padding: 8px 18px;
    border-radius: 7px;
}}
QPushButton {{
    background: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 12px;
}}
QPushButton:hover {{
    background: #252e35;
}}
QPushButton#Accent {{
    background: {GOLD};
    color: #111;
    font-weight: 800;
    border: none;
}}
QPushButton#Accent:hover {{
    background: {GOLD2};
}}
QPushButton#Nav {{
    border: none;
    border-radius: 0;
    padding: 13px 16px;
    background: transparent;
    color: #d8dde1;
}}
QPushButton#Nav:checked {{
    color: {GOLD};
    background: #20272d;
    border-top: 3px solid {GOLD};
}}
QLineEdit, QComboBox, QTextEdit {{
    background: {FIELD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
}}
QComboBox QAbstractItemView {{
    background: {FIELD};
    border: 1px solid {GOLD};
    selection-background-color: #8a6710;
}}
QTableView {{
    background: {PANEL};
    alternate-background-color: #11171c;
    gridline-color: #242b31;
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: #725d1d;
    selection-color: white;
}}
QHeaderView::section {{
    background: #20272d;
    color: {TEXT};
    padding: 7px;
    border: none;
    border-right: 1px solid #2d343a;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {PANEL};
}}
QTabBar::tab {{
    background: transparent;
    padding: 10px 16px;
}}
QTabBar::tab:selected {{
    color: {GOLD};
    border-bottom: 2px solid {GOLD};
}}
"""

class DbStore:
    @staticmethod
    def connect():
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    @staticmethod
    def rows(sql, args=()):
        with DbStore.connect() as con:
            return con.execute(sql, args).fetchall()

    @staticmethod
    def columns(table):
        with DbStore.connect() as con:
            return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def action_received_column():
        cols=DbStore.columns("actions")
        if "received_at" in cols:return "received_at"
        if "received_date" in cols:return "received_date"
        return "created_at" if "created_at" in cols else "id"

class RequestDialog(QDialog):
    def __init__(self, parent=None, row=None):
        super().__init__(parent)
        self.setWindowTitle("Poptávka – úprava" if row else "Nová poptávka")
        self.resize(900, 680)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        general = QWidget()
        form = QFormLayout(general)
        self.action = QComboBox(); self.action.setEditable(True)
        self.company = QComboBox(); self.company.setEditable(True)
        self.subject = QLineEdit()
        self.status = QComboBox(); self.status.addItems(["Čekám","Obdrženo","Bez odezvy","Archivováno"])
        self.assigned = QComboBox(); self.assigned.setEditable(True)
        self.note = QTextEdit()

        companies = [r["official_name"] for r in DbStore.rows("SELECT official_name FROM companies WHERE active=1 ORDER BY official_name")]
        users = [r["name"] for r in DbStore.rows("SELECT name FROM users WHERE active=1 ORDER BY name")]
        actions = [r["name"] for r in DbStore.rows("SELECT DISTINCT name FROM actions WHERE trim(coalesce(name,''))<>'' ORDER BY name")]
        self.company.addItems(companies); self.assigned.addItems(users); self.action.addItems(actions)

        form.addRow("Akce / Příležitost", self.action)
        form.addRow("Společnost", self.company)
        form.addRow("Předmět", self.subject)
        form.addRow("Stav", self.status)
        form.addRow("Řeší", self.assigned)
        form.addRow("Poznámka", self.note)
        tabs.addTab(general, "Obecné")

        recipients = QWidget(); recipients.setLayout(QVBoxLayout()); tabs.addTab(recipients,"Příjemci")
        notes = QWidget(); notes.setLayout(QVBoxLayout()); tabs.addTab(notes,"Poznámky")

        hist = QWidget(); hv = QVBoxLayout(hist)
        table = QTableView(); hv.addWidget(table)
        tabs.addTab(hist,"Historie")

        buttons = QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        save_btn = buttons.button(QDialogButtonBox.Save); save_btn.setText("Uložit"); save_btn.setObjectName("Accent")
        buttons.button(QDialogButtonBox.Cancel).setText("Zrušit")
        root.addWidget(buttons)

class Page(QWidget):
    def __init__(self, title, create_text=None, create_cb=None):
        super().__init__()
        self.layout = QVBoxLayout(self)
        head = QHBoxLayout()
        lab = QLabel(title); lab.setObjectName("Title")
        head.addWidget(lab); head.addStretch()
        if create_text:
            btn = QPushButton(create_text); btn.setObjectName("Accent")
            if create_cb: btn.clicked.connect(create_cb)
            head.addWidget(btn)
        self.layout.addLayout(head)

class RequestsPage(Page):
    def __init__(self, main):
        super().__init__("Poptávky","+ Nová poptávka",lambda: RequestDialog(main).exec())
        split = QSplitter()
        split.setOrientation(Qt.Horizontal)
        self.layout.addWidget(split,1)

        left = QFrame(); left.setObjectName("Panel")
        lv = QVBoxLayout(left)
        fl = QLabel("Filtry"); fl.setStyleSheet("font-weight:700")
        lv.addWidget(fl)
        self.user = QComboBox(); self.company=QComboBox(); self.status=QComboBox()
        self.search = QLineEdit(); self.search.setPlaceholderText("Hledat...")
        self.status.addItems(["(vše)","Čekám","Obdrženo","Bez odezvy","Archivováno"])
        for w in [self.user,self.company,self.status,self.search]: lv.addWidget(w)
        lv.addStretch()
        split.addWidget(left)

        center = QFrame(); center.setObjectName("Panel")
        cv = QVBoxLayout(center)
        self.model = QStandardItemModel(0,7)
        self.model.setHorizontalHeaderLabels(["Datum","Odběratel","Dodavatel","Akce","Poptáváno","Řeší","Stav"])
        self.table = QTableView(); self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.doubleClicked.connect(self.edit_current)
        cv.addWidget(self.table)
        split.addWidget(center)

        right = QFrame(); right.setObjectName("Panel")
        rv = QVBoxLayout(right); rv.addWidget(QLabel("Historie poptávek"))
        self.hist = QTableView(); rv.addWidget(self.hist)
        split.addWidget(right)
        split.setSizes([230,900,320])
        self.reload()

    def reload(self):
        rows = DbStore.rows("""SELECT r.id,r.asked_date,cf.official_name odb,c.official_name dod,a.name akce,
                                 r.item,r.assigned_user,r.received_date,r.no_response,r.archived
                          FROM requests r
                          LEFT JOIN companies c ON c.id=r.company_id
                          LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                          LEFT JOIN actions a ON a.id=r.action_id
                          ORDER BY r.asked_date DESC,r.id DESC LIMIT 300""")
        self.model.setRowCount(0)
        for r in rows:
            status = "Archivováno" if r["archived"] else ("Bez odezvy" if r["no_response"] else ("Obdrženo" if r["received_date"] else "Čekám"))
            vals = [r["asked_date"] or "",r["odb"] or "",r["dod"] or "",r["akce"] or "",r["item"] or "",r["assigned_user"] or "",status]
            items = [QStandardItem(str(v)) for v in vals]
            items[0].setData(r["id"],Qt.UserRole)
            if status=="Obdrženo":
                for it in items: it.setBackground(QColor("#183126"))
            elif status=="Čekám":
                for it in items: it.setBackground(QColor("#3a3117"))
            self.model.appendRow(items)

    def edit_current(self):
        idx = self.table.currentIndex()
        if not idx.isValid(): return
        rid = self.model.item(idx.row(),0).data(Qt.UserRole)
        rows = DbStore.rows("""SELECT r.*,c.official_name company,a.name action_name
                          FROM requests r
                          LEFT JOIN companies c ON c.id=r.company_id
                          LEFT JOIN actions a ON a.id=r.action_id WHERE r.id=?""",(rid,))
        RequestDialog(self, rows[0] if rows else None).exec()

class SimpleTablePage(Page):
    def __init__(self, title, sql, headers, create_text=None):
        super().__init__(title,create_text,None)
        self.sql=sql; self.headers=headers
        self.model=QStandardItemModel(0,len(headers)); self.model.setHorizontalHeaderLabels(headers)
        self.table=QTableView(); self.table.setModel(self.model); self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.layout.addWidget(self.table,1); self.reload()
    def reload(self):
        rows=DbStore.rows(self.sql)
        self.model.setRowCount(0)
        for r in rows:
            self.model.appendRow([QStandardItem(str(v or "")) for v in r])

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1600,940)
        self.setMinimumSize(1220,720)
        root = QWidget(); self.setCentralWidget(root)
        lay = QVBoxLayout(root); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        top = QFrame(); top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.addWidget(QLabel(f"{APP_NAME} v{APP_VERSION}"))
        self.test = QLabel("⚗ TESTOVACÍ REŽIM – ZMĚNY SE NEUKLÁDAJÍ"); self.test.setObjectName("TestBanner"); self.test.hide()
        tl.addStretch(); tl.addWidget(self.test); tl.addStretch()
        self.userbtn = QPushButton("TEST  ▾" if False else "Uživatel  ▾")
        tl.addWidget(self.userbtn); tl.addWidget(QPushButton("⚙"))
        lay.addWidget(top)

        nav = QFrame(); nav.setObjectName("NavBar"); nl=QHBoxLayout(nav); nl.setContentsMargins(10,0,10,0)
        self.stack = QStackedWidget()
        self.pages = {}
        _received=DbStore.action_received_column()
        defs = [
            ("Přehled", SimpleTablePage("Přehled",f"SELECT status,{_received},name,updated_by FROM actions ORDER BY id DESC LIMIT 100",["Stav","Datum","Příležitost","Řeší"])),
            ("Příležitosti / Akce", SimpleTablePage("Příležitosti / Akce",f"SELECT status,{_received},name,updated_by FROM actions ORDER BY {_received} DESC,id DESC",["Stav","Přijato","Příležitost","Řeší"],"+ Nová příležitost")),
            ("Poptávky", RequestsPage(self)),
            ("Úkoly", SimpleTablePage("Úkoly","SELECT due_date,text,assigned_user,done FROM tasks ORDER BY due_date",["Termín","Úkol","Řeší","Hotovo"],"+ Nový úkol")),
            ("Společnosti", SimpleTablePage("Společnosti","SELECT official_name,ico,address,active FROM companies ORDER BY official_name",["Oficiální název","IČO","Sídlo","Aktivní"],"+ Nová společnost")),
            ("Osoby", SimpleTablePage("Osoby","SELECT name,email,phone,role FROM people ORDER BY name",["Jméno","E-mail","Telefon","Funkce"],"+ Nová osoba")),
        ]
        for i,(name,page) in enumerate(defs):
            self.pages[name]=page; self.stack.addWidget(page)
            b=QPushButton(name); b.setCheckable(True); b.setObjectName("Nav")
            b.clicked.connect(lambda checked,idx=i,btn=b:self.switch(idx,btn))
            nl.addWidget(b)
            if i==0: b.setChecked(True); self.active_nav=b
        nl.addStretch()
        lay.addWidget(nav); lay.addWidget(self.stack,1)

        foot = QHBoxLayout()
        creator=QLabel("vytvořil Ing. Jaroslav Kučera"); creator.setStyleSheet(f"color:{GOLD};font-weight:700")
        foot.addWidget(creator); foot.addStretch()
        foot.addWidget(QLabel("Databáze: zakazky.db (schéma 5.0)"))
        fw=QWidget(); fw.setLayout(foot); lay.addWidget(fw)

    def switch(self,idx,btn):
        self.stack.setCurrentIndex(idx)
        if hasattr(self,"active_nav"): self.active_nav.setChecked(False)
        btn.setChecked(True); self.active_nav=btn

def fatal_startup_error(exc):
    import traceback
    try:
        log = ROOT / "v5_error.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        log = None
    try:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "ZakázkyApp v5 – chyba při spuštění",
                             f"Program se nepodařilo spustit.\n\n{exc}\n\n"
                             + (f"Podrobnosti: {log}" if log else ""))
    except Exception:
        pass

def main():
    ensure_schema()
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setFont(QFont("Calibri",11))
    w = MainWindow(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        fatal_startup_error(exc)
        raise
