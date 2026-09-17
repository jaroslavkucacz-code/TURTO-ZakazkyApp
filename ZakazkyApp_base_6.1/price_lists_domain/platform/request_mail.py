"""Request mail profiles, explicit writes and per-request snapshots."""
import re
import tkinter as tk
from tkinter import ttk, messagebox

DEFAULT_BODY = "Dobrý den,\n\n\n\nPředem velice děkuji,"
PROFILE_KEY = "request_mail_body"
URGENT_PREFIX = "SPĚCHÁ! "


def text_lf(value):
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def with_urgency(subject, urgent):
    base = re.sub(r"^(?:SPĚCHÁ!\s*)+", "", subject or "", flags=re.IGNORECASE)
    return (URGENT_PREFIX if urgent else "") + base


def flag(value):
    return str(value).strip().casefold() in ("1", "true")


def technical_user(name):
    return (name or "").strip().casefold() in ("test", "admin")


def users(con):
    return [r[0] for r in con.execute(
        "SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")
        if r[0] and r[0].strip() and not technical_user(r[0])]


def logged_in_user(M, widget):
    app = M.find_app(widget)
    variable = getattr(app, "active_user", None)
    return variable.get() if variable is not None else M.get_setting("active_user", "")


def default_user(M, widget, eligible):
    name = logged_in_user(M, widget)
    return name if name in eligible else ""


def validate_user(con, name, original=""):
    name = (name or "").strip()
    if name and name != original and name not in users(con):
        raise ValueError("Vyberte aktivního uživatele ze seznamu. TEST a Admin nelze zvolit.")
    return name


def profile(M, name):
    if not name or technical_user(name):
        return DEFAULT_BODY
    value = M.get_user_setting(name, PROFILE_KEY, DEFAULT_BODY)
    return text_lf(value if value is not None else DEFAULT_BODY)


def save_profile(M, name, body, expected):
    """Only the explicit profile Save calls this; reject a concurrent overwrite."""
    with M.db() as con:
        if name not in users(con):
            raise ValueError("Vyberte aktivního uživatele. TEST a Admin nemají text poptávky.")
        row = con.execute("SELECT value FROM user_settings WHERE user_name=? AND key=?",
                          (name, PROFILE_KEY)).fetchone()
        current = text_lf(row[0]) if row and row[0] is not None else DEFAULT_BODY
        if current != expected:
            raise ValueError("Výchozí text mezitím změnil jiný uživatel. Zavřete okno a načtěte jej znovu.")
        con.execute("INSERT OR REPLACE INTO user_settings(user_name,key,value) VALUES(?,?,?)",
                    (name, PROFILE_KEY, text_lf(body)))


def body_for_request(M, row):
    row = dict(row)
    body = row.get("mail_body")
    return profile(M, row.get("assigned_user", "")) if body is None else text_lf(body)


class ProfileDialog(tk.Toplevel):
    def __init__(self, parent, M, user_name):
        super().__init__(parent)
        self.M, self.user_name, self.result = M, user_name, None
        self.title("Výchozí text poptávky")
        M.enable_dialog_maximize(self, 720, 420)
        self.transient(parent)
        self.grab_set()
        self.original = profile(M, user_name)
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"Poptávající: {user_name}").pack(anchor="w")
        ttk.Label(frame, text="Tento text se nabídne v nových poptávkách uživatele.").pack(anchor="w", pady=(4, 10))
        self.body = tk.Text(frame, wrap="word", height=10, undo=True)
        self.body.pack(fill="both", expand=True)
        self.body.insert("1.0", self.original)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Zrušit", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Uložit výchozí text", command=self.save,
                   style="Accent.TButton").pack(side="right")
        # Enter belongs to the text editor; saving is always explicit.
        self.bind("<Escape>", lambda e: self.destroy())

    def save(self):
        body = self.body.get("1.0", "end-1c")
        try:
            save_profile(self.M, self.user_name, body, self.original)
        except ValueError as exc:
            return messagebox.showwarning("Výchozí text poptávky", str(exc), parent=self)
        self.result = body
        self.destroy()
