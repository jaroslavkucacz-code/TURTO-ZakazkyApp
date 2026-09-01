"""General settings dialog for issued offers."""
from __future__ import annotations

from pathlib import Path

from . import service


_FIELDS = (
    ("Název vystavovatele", "issued_offer_issuer_name", "TURTO s.r.o."),
    ("Adresa vystavovatele", "issued_offer_issuer_address", "Kaprova 42/14, 110 00 Praha 1"),
    ("IČ", "issued_offer_issuer_ico", "24196231"),
    ("DIČ", "issued_offer_issuer_dic", "CZ24196231"),
    ("Kontaktní osoba", "issued_offer_issuer_contact", ""),
    ("E-mail", "issued_offer_issuer_email", "info@turto.cz"),
    ("Telefon", "issued_offer_issuer_phone", ""),
    ("Bankovní spojení", "issued_offer_issuer_bank", ""),
    ("Výchozí platnost [dní]", "issued_offer_default_validity_days", "14"),
    ("Výchozí DPH [%]", "issued_offer_default_vat_rate", "21"),
    ("Výchozí měna", "issued_offer_default_currency", "CZK"),
)


def open_settings(M, app):
    win = M.tk.Toplevel(app)
    win.title("Nastavení vydaných nabídek")
    win.transient(app)
    win.grab_set()
    M.enable_dialog_maximize(win, 1040, 760)
    outer = M.scrollable_dialog_frame(win, 16)
    outer.columnconfigure(1, weight=1)
    M.ttk.Label(outer, text="Vydané nabídky", font=("Calibri", 16, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 4)
    )
    M.ttk.Label(
        outer,
        text="Číslování je pevné: CNrr-00000 (např. CN26-00001). Rok i pořadí doplní program.",
        style="PageSubtitle.TLabel",
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
    variables = {}
    row = 2
    for label, key, default in _FIELDS:
        variable = M.tk.StringVar(value=service.get_setting(M, key, default))
        variables[key] = variable
        M.ttk.Label(outer, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        if key == "issued_offer_default_currency":
            widget = M.safe_combobox(outer, textvariable=variable, values=["CZK", "EUR", "PLN"], state="readonly")
        else:
            widget = M.ttk.Entry(outer, textvariable=variable)
        widget.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        row += 1

    M.ttk.Label(outer, text="Trvalý archiv PDF").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
    archive = M.tk.StringVar(value=str(service.archive_root(M)))
    M.ttk.Entry(outer, textvariable=archive).grid(row=row, column=1, sticky="ew", pady=4)

    def choose_archive():
        selected = M.filedialog.askdirectory(parent=win, initialdir=archive.get() or str(service.archive_root(M)))
        if selected:
            archive.set(selected)

    M.ttk.Button(outer, text="Vybrat…", command=choose_archive).grid(row=row, column=2, sticky="w", padx=(6, 0))
    row += 1

    multiline = (
        ("Výchozí platební podmínky", "issued_offer_default_payment_terms", "Splatnost 30 dní."),
        ("Výchozí dodací podmínky", "issued_offer_default_delivery_terms", ""),
        ("Výchozí termín dodání", "issued_offer_default_delivery_time", ""),
        ("Výchozí poznámka zákazníkovi", "issued_offer_default_customer_note", ""),
    )
    texts = {}
    for label, key, default in multiline:
        M.ttk.Label(outer, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=4)
        text = M.tk.Text(outer, height=4, wrap="word", font=("Calibri", 10))
        text.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        text.insert("1.0", service.get_setting(M, key, default))
        texts[key] = text
        row += 1

    buttons = M.ttk.Frame(outer)
    buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(14, 0))

    def save():
        try:
            validity = int(service.number(variables["issued_offer_default_validity_days"].get(), 14))
            vat = service.number(variables["issued_offer_default_vat_rate"].get(), 21)
            if validity < 1 or validity > 3650 or vat < 0 or vat > 100:
                raise ValueError("Zkontrolujte výchozí platnost a sazbu DPH.")
            for _label, key, _default in _FIELDS:
                service.set_setting(M, key, variables[key].get().strip())
            root = Path(archive.get().strip())
            root.mkdir(parents=True, exist_ok=True)
            service.set_setting(M, "issued_offer_archive_root", root)
            for key, widget in texts.items():
                service.set_setting(M, key, widget.get("1.0", "end-1c").strip())
            win.destroy()
        except Exception as exc:
            M.messagebox.showwarning("Vydané nabídky", str(exc), parent=win)

    M.ttk.Button(buttons, text="Zrušit", command=win.destroy).pack(side="right")
    M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right", padx=(0, 6))


def install(M):
    M.App.open_issued_offer_settings = lambda self: open_settings(M, self)


__all__ = ["open_settings", "install"]
