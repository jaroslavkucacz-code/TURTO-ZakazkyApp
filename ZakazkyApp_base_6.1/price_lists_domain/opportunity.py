"""Direct + Nová Akce integration for the Příležitost dialog."""
from __future__ import annotations
from . import context as ctx

def _install_new_project_button(module):
    Dialog = module.ActionDialog
    if getattr(Dialog, "_turto_price_list_project_button", False):
        return
    old_init = Dialog.__init__

    def create_project(self):
        dialog = module.ProjectDialog(self)
        self.wait_window(dialog)
        try:self.grab_set()
        except Exception:pass
        if not dialog.result:
            return
        with module.db() as con:
            row = con.execute("SELECT id,name FROM projects WHERE id=?", (dialog.result,)).fetchone()
            projects = con.execute("SELECT id,name FROM projects WHERE active=1 ORDER BY name COLLATE CZECH").fetchall()
        self.projects = list(projects)
        try:self.action_name_box.set_values([r["name"] for r in projects])
        except Exception:pass
        if row:
            self.name.set(row["name"])
            try:self.action_name_box.focus_set()
            except Exception:pass

    def init(self, *args, **kwargs):
        old_init(self, *args, **kwargs)
        try:
            parent = self.action_name_box.master
            button = module.ttk.Button(parent, text="+ Nová Akce", command=lambda: create_project(self))
            button.grid(row=0, column=2, sticky="e", padx=(6, 0), pady=5)
        except Exception:
            pass

    Dialog.new_project_from_opportunity = create_project
    Dialog.__init__ = init
    Dialog._turto_price_list_project_button = True
