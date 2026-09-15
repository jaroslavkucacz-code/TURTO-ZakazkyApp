"""Input-only Tab traversal and explicit, non-destructive form closing."""
from __future__ import annotations

import copy
import tkinter as tk

TAG = 'TurtoInputTraversal817'
INPUT_CLASSES = {'Entry', 'TEntry', 'TCombobox', 'Spinbox', 'TSpinbox', 'Text'}


def children(win):
    """One form only; child dialogs and suggestion windows own their state."""
    for child in win.winfo_children():
        if isinstance(child, tk.Toplevel):
            continue
        yield child
        yield from children(child)


def editable(widget):
    try:
        if hasattr(widget, 'instate') and (widget.instate(['disabled']) or widget.instate(['readonly'])):
            return False
        return (widget.winfo_class() in INPUT_CLASSES
                and widget.winfo_viewable()
                and str(widget.cget('state')) == 'normal')
    except tk.TclError:
        return False


def values(win):
    result = {}
    for widget in children(win):
        cls = widget.winfo_class()
        try:
            if cls == 'Text' and str(widget.cget('state')) != 'disabled':
                result[str(widget)] = widget.get('1.0', 'end-1c')
            elif cls in INPUT_CLASSES - {'Text'}:
                result[str(widget)] = widget.get()
            elif cls in {'Checkbutton', 'TCheckbutton', 'Radiobutton', 'TRadiobutton'}:
                variable = str(widget.cget('variable'))
                if variable:
                    result['var:' + variable] = str(widget.getvar(variable))
        except tk.TclError:
            continue
    if hasattr(win, 'selected_topics'):
        result['topics'] = tuple(win.selected_topics)
    return result


def wire_close(win, close):
    """Bind user close paths, without intercepting destroy or successful saves."""
    win._turto_form_close = close
    win.protocol('WM_DELETE_WINDOW', close)
    win.bind('<Escape>', lambda event=None: (close(), 'break')[1])
    for widget in children(win):
        if widget.winfo_class() not in {'Button', 'TButton'}:
            continue
        if str(widget.cget('text')).strip().casefold() in {'zrušit', 'zavřít'}:
            widget.configure(command=close)


class FormGuard:
    def __init__(self, M, win, save, snapshot=None, close=None):
        self.M, self.win, self.save = M, win, save
        self.snapshot = snapshot or (lambda: values(win))
        self.close = close or win.destroy
        self.busy = False
        self.mark_saved()
        win._turto_form_guard = self
        wire_close(win, self.request_close)

    def mark_saved(self):
        self.baseline = copy.deepcopy(self.snapshot())

    def changed(self):
        return self.snapshot() != self.baseline

    def request_close(self):
        if self.busy or not self.win.winfo_exists():
            return False
        self.busy = True
        focus = self.win.focus_get()
        try:
            if self.changed():
                answer = self.M.messagebox.askyesnocancel(
                    'Neuložené změny',
                    'Chcete uložit změny před zavřením?\n\n'
                    'Ano = uložit a zavřít\nNe = zahodit změny\n'
                    'Zrušit = pokračovat v úpravách', parent=self.win)
                if answer is None:
                    return False
                if answer:
                    saved = self.save()
                    if not self.win.winfo_exists():
                        return True
                    # Validation failure or a cancelled secondary save dialog
                    # must leave the draft open. Persistent editors explicitly
                    # mark their successful save; close-on-save forms destroy.
                    if saved is not True and self.changed():
                        return False
            self.close()
            return not self.win.winfo_exists()
        except Exception as exc:
            if self.win.winfo_exists():
                self.M.messagebox.showerror('Uložení změn',
                    f'Okno zůstává otevřené. Změny se nepodařilo uložit:\n\n{exc}',
                    parent=self.win)
            return False
        finally:
            self.busy = False
            try:
                if self.win.winfo_exists() and focus is not None and focus.winfo_viewable():
                    focus.focus_set()
            except tk.TclError:
                pass


def mark_saved(win):
    guard = getattr(win, '_turto_form_guard', None)
    if guard is not None:
        guard.mark_saved()


def register(M, win, save, snapshot=None, close=None):
    guard = getattr(win, '_turto_form_guard', None)
    if guard is None:
        guard = FormGuard(M, win, save, snapshot, close)
    return guard


def traverse(M, event, backwards=False):
    source = event.widget
    # Tab from a suggestion list continues in the owning form, without
    # committing a suggestion merely because the user moved to another field.
    for entry in tuple(getattr(M, '_AUTOCOMPLETE_ENTRIES', ())):
        if source is entry or source is getattr(entry, 'listbox', None):
            entry.hide()
            source = entry
            break
    top = source.winfo_toplevel()
    fields = [widget for widget in children(top) if editable(widget)]
    if not fields:
        return 'break'
    if source in fields:
        index = (fields.index(source) + (-1 if backwards else 1)) % len(fields)
    else:
        ordered = list(children(top))
        origin = ordered.index(source) if source in ordered else (-1 if not backwards else len(ordered))
        candidates = [w for w in fields if (ordered.index(w) < origin if backwards else ordered.index(w) > origin)]
        target = (candidates[-1] if backwards else candidates[0]) if candidates else (fields[-1] if backwards else fields[0])
        index = fields.index(target)
    target = fields[index]
    target.focus_set()
    # Scrollable forms must reveal the destination as well as focus it.
    canvas = getattr(top, '_dialog_canvas', None)
    if canvas is not None and canvas.winfo_viewable():
        y = target.winfo_rooty() - canvas.winfo_rooty()
        height = canvas.winfo_height()
        if y < 0 or y + target.winfo_height() > height:
            bounds = canvas.bbox('all')
            if bounds and bounds[3] > 0:
                canvas.yview_moveto(max(0, (canvas.canvasy(0) + y - height / 3) / bounds[3]))
    return 'break'


def discover(M, win):
    if not win.winfo_exists() or win.overrideredirect() or hasattr(win, '_turto_form_close'):
        return
    buttons = [w for w in children(win) if w.winfo_class() in {'Button', 'TButton'}
               and str(w.cget('text')).strip().casefold().startswith('uložit')]
    if buttons:
        primary = next((w for w in buttons if str(w.cget('text')).strip().casefold() == 'uložit'), buttons[0])
        register(M, win, primary.invoke)


def apply(M):
    if getattr(M, '_turto_form_behavior_817', False):
        return
    M._turto_form_behavior_817 = True

    # The six normal edit dialogs finish all historical constructor layers
    # before capturing the initial values. Programmatic destroy remains native.
    def wrap_dialog(cls):
        previous = cls.__init__
        def init(self, *args, **kwargs):
            previous(self, *args, **kwargs)
            register(M, self, self.ok).mark_saved()
        cls.__init__ = init
    for name in ('CompanyDialog', 'PersonDialog', 'ProjectDialog', 'TaskDialog', 'ActionDialog', 'RequestDialog'):
        wrap_dialog(getattr(M, name))

    notes = M.UserNotesDialog
    previous_notes = notes.__init__
    def notes_init(self, *args, **kwargs):
        previous_notes(self, *args, **kwargs)
        register(M, self, self.save_note,
                 lambda: (self.editing_id, self.editor.get('1.0', 'end-1c')), self.close)
    notes.__init__ = notes_init
    def wrap_note(method):
        def changed(self, *args, **kwargs):
            result = method(self, *args, **kwargs)
            mark_saved(self)
            return result
        return changed
    notes.clear_editor = wrap_note(notes.clear_editor)
    notes.edit_selected = wrap_note(notes.edit_selected)

    previous_init = M.App.__init__
    def init(self, *args, **kwargs):
        previous_init(self, *args, **kwargs)
        self.bind_class(TAG, '<Tab>', lambda e: traverse(M, e, bool(e.state & 1)))
        self.bind_class(TAG, '<Shift-Tab>', lambda e: traverse(M, e, True))
        self.bind_class(TAG, '<ISO_Left_Tab>', lambda e: traverse(M, e, True))
        def escape_inline(event):
            current = event.widget
            while current is not None:
                if isinstance(current, M.InlineChoice) and getattr(current, '_shown', False):
                    current.hide()
                    return 'break'
                current = getattr(current, 'master', None)
        self.bind_class(TAG, '<Escape>', escape_inline)

        def mapped(event):
            widget = event.widget
            if not isinstance(widget, tk.Misc):
                return
            tags = widget.bindtags()
            if TAG not in tags:
                widget.bindtags((TAG, *tags))
            if isinstance(widget, tk.Toplevel) and not widget.overrideredirect():
                if not getattr(widget, '_turto_form_discovery_pending', False):
                    widget._turto_form_discovery_pending = True
                    def ready():
                        widget._turto_form_discovery_pending = False
                        discover(M, widget)
                    self.after_idle(ready)
        self.bind_all('<Map>', mapped, add='+')
        def initial_walk(widget):
            mapped(type('Mapped', (), {'widget': widget})())
            for child in widget.winfo_children():
                initial_walk(child)
        initial_walk(self)
    M.App.__init__ = init

    previous_close = M.App.close_app
    def close_app(self):
        # Closing the main window must not silently destroy an open editor.
        def close_children(parent):
            for child in tuple(parent.winfo_children()):
                if not close_children(child):
                    return False
                close = getattr(child, '_turto_form_close', None)
                if close is not None and child.winfo_exists():
                    close()
                    if child.winfo_exists():
                        return False
            return True
        if close_children(self):
            return previous_close(self)
    M.App.close_app = close_app
