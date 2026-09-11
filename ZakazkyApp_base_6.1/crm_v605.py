# TURTO CRM v6.0.5 incremental features
M=None

LATE_FONT_TREES=(
    'dash_tree','dash_tasks_tree','dash_requests_tree',
    'action_tree','request_tree','mivo_tree','offer_tree','task_tree',
    'project_tree','people_tree','company_tree',
    'price_current_tree','price_list_evidence_tree','issued_offer_tree',
)

# v611_audit is the single action snapshot owner. It includes `status` and
# preserves the historical entity/action/field/undo contract for status changes
# (Příležitost / Změna stavu / Stav). The former v605 SELECT id,status snapshot
# is intentionally retired so each Příležitosti refresh reads actions once.
#
# v628/lazy_refresh are the later navigation owners and already reset temporary
# Treeview sorting when a page changes, so the historical v605 show_page wrapper
# is intentionally retired as well.
#
# recipient_usage is owned/created by the later v608_stability layer before App
# is instantiated. Keeping the same CREATE TABLE here opened an extra database
# connection during every startup without changing the final schema.

# v608_stability is the later owner of MIVO row state and the >10-day warning.
# The old v605 pass parsed the first number from the displayed date and recolored
# every MIVO row, only for v608 to overwrite those tags immediately afterwards.
# It is intentionally retired rather than kept as a duplicate full-table scan.


def _patch_late_font():
    """Preserve v605's unique late-row font without repainting the whole UI."""
    old=M.App.apply_theme

    def apply_late_font(app):
        for name in LATE_FONT_TREES:
            tree=getattr(app,name,None)
            if tree is None:continue
            try:tree.tag_configure('status_late',font=('Calibri',10,'bold'))
            except Exception:pass

    def theme(self,*a,**k):
        r=old(self,*a,**k)
        try:self.after_idle(lambda:apply_late_font(self))
        except Exception:apply_late_font(self)
        return r

    theme._turto_v605_late_font_only=True
    M.App.apply_theme=theme


def apply(module):
    global M;M=module;_patch_late_font()
