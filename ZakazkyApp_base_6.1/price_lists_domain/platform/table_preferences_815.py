"""Stable table identities and event-driven registration of future dialogs.

Only UI preferences live in user_settings beside the business data. Tk widget
commands stay native; no recurring scans or writes on geometry/paint events.
"""
from __future__ import annotations

import hashlib
import weakref


def key_for(tree):
    identity = getattr(tree, '_turto_layout_id', None)
    if not identity:
        root = tree._root()
        # Shared table factories serve several pages. Public main-window
        # attributes give each one a distinct role, independent of its schema.
        for name, value in vars(root).items():
            if value is tree and name.endswith('_tree'):
                identity = 'main.' + name
                break
        if not identity:
            name = str(getattr(tree, '_name', ''))
            if name.startswith('layout__'):
                identity = name
            else:
                # Compatibility for external/older builders. Current bundled
                # builders all declare a stable name (checked in CI).
                top = tree.winfo_toplevel()
                identity = type(top).__module__ + '.' + type(top).__qualname__
                identity += '|' + '|'.join(map(str, tree.cget('columns')))
        tree._turto_layout_id = identity
    digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
    return 'tree_layout_v815_' + digest


def apply(M):
    if getattr(M, '_turto_table_preferences_815', False):
        return
    previous_init = M.App.__init__
    previous_user_changed = getattr(M.App, 'on_user_changed', None)

    def register(app, tree):
        if not isinstance(tree, M.ttk.Treeview) or not tree.winfo_exists():
            return
        first = tree not in app._turto_preference_tables
        if first:
            app._turto_preference_tables.add(tree)
        # The column-settings listing is a control surface, not a business
        # table: hiding its own controls would make it impossible to operate.
        controls = 'columns_dialog' in str(getattr(tree, '_name', ''))
        if not controls:
            tree._turto_configurable_columns = True
        # Builders may apply their initial column preset after an older layer
        # loaded preferences. Reconcile once after the builder has finished.
        M.install_persistent_tree_layout(tree, force=first)
        if not controls and str(tree.cget('show')).find('headings') >= 0:
            M.install_v760_tree_polish(tree)

    def init(self, *args, **kwargs):
        result = previous_init(self, *args, **kwargs)
        self._turto_preference_tables = weakref.WeakSet()

        def mapped(event):
            register(self, event.widget)

        # A class binding sees only Treeviews, including future nested dialogs.
        # Existing widget/class mouse handlers remain intact.
        self.bind_class('Treeview', '<Map>', mapped, add='+')
        stack = [self]
        while stack:
            widget = stack.pop()
            if isinstance(widget, M.ttk.Treeview):
                register(self, widget)
            stack.extend(widget.winfo_children())
        return result

    M.App.__init__ = init
    if callable(previous_user_changed):
        def user_changed(self, *args, **kwargs):
            result = previous_user_changed(self, *args, **kwargs)
            for tree in tuple(getattr(self, '_turto_preference_tables', ())):
                if tree.winfo_exists():
                    register(self, tree)
            return result
        M.App.on_user_changed = user_changed
    M._turto_table_preferences_815 = True
