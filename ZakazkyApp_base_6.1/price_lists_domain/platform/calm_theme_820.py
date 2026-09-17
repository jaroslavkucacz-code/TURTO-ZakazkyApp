"""Shared TURTO palette and bounded, presentation-only Treeview cell badges.

Native rows, values, selection, sorting and export remain authoritative. Only
visible status/deadline cells get decorations; no polling or Tcl command proxy.
"""
from __future__ import annotations

from datetime import date, datetime
import tkinter as tk
from tkinter import ttk, font as tkfont
from .universal_search import match_ranges

LIGHT = dict(bg='#F4F5F7', panel='#FFFFFF', field='#FFFFFF', fg='#263442',
             muted='#667585', head='#EDF0F3', select='#E6EDF5', border='#DDE3E9',
             card='#FFFFFF', alternate='#FAFBFC', topbar='#FFFFFF', navbar='#26323C',
             accent='#B71926', hover='#991520', selection_fg='#263442')
DARK = dict(bg='#182129', panel='#222D37', field='#202A34', fg='#E8EEF4',
            muted='#B0BECC', head='#2A3642', select='#344E66', border='#3A4856',
            card='#202A34', alternate='#242F3A', topbar='#F4F5F7', navbar='#131C24',
            accent='#B71926', hover='#991520', selection_fg='#FFFFFF')
SEARCH = {
    False: dict(panel='#FFF7DF', ink='#745211', match='#FFE39A', chip='#F6E3AC'),
    True: dict(panel='#393426', ink='#F2D68A', match='#665026', chip='#51452A'),
}
BADGES = {
    False: dict(active=('#EAF1F8', '#315F87'), ready=('#E8F3F0', '#286C68'),
                done=('#EBF3EC', '#386A43'), wait=('#FBF2DF', '#826016'),
                late=('#FBEDEF', '#AC343F'), cancel=('#EDF0F3', '#566372')),
    True: dict(active=('#2A4055', '#B7D7F5'), ready=('#25433F', '#A6DCD1'),
               done=('#2E4234', '#BDDDBF'), wait=('#443B28', '#EDCE8D'),
               late=('#4B3038', '#FFC0C6'), cancel=('#343E48', '#D0D9E2')),
}
ROW_TAGS = set('status_active status_offer status_wait status_done status_won status_cancel status_late status_soon req_fresh req_mid req_old req_received late soon waiting done won lost info over today wait deadline_urgent warning_bold v770_deadline_attention v770_request_attention v7616_request_attention mivo_wait_7'.split())
STATUS_COLUMNS = {'stav', 'status', 'stav nabídky', 'stav poptávky'}
DATE_COLUMNS = {'deadline', 'termín', 'termin', 'poptáno', 'kdy'}
PRICE_KINDS = dict(price_current='ready', price_future='active', price_expiring='wait',
                   price_review='wait', price_expired='late', price_archived='cancel')
ROW_TAGS.update(PRICE_KINDS)
ROW_TAGS.update(('offer_archived', 'offer_unassigned', 'offer_uncategorized', 'offer_pricelist'))
ROW_TAGS.add('req_overdue_bold')
STATUS_COLUMNS.update(('platnost', 'vazba', 'zařazení produktů'))


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def palette(widget):
    root = widget._root()
    theme = getattr(root, 'theme', None)
    dark = theme is not None and str(theme.get()) == 'Tmavý'
    return DARK if dark else LIGHT


def status_kind(value):
    value = str(value).strip().casefold()
    if any(word in value for word in ('zrušen', 'archiv', 'zamítnut', 'prohrán')):
        return 'cancel'
    if any(word in value for word in ('po termínu', 'po platnosti', 'chyba')):
        return 'late'
    if any(word in value for word in ('hotov', 'dokončen', 'vyhrán', 'uzavřen', 'splněn')):
        return 'done'
    if any(word in value for word in ('připraven', 'obdržen', 'přijat', 'platn', 'v pořádku')):
        return 'ready'
    if any(word in value for word in ('ček', 'kontrol', 'končí', 'návrh', 'dnes', 'brzy', 'nepřiřazen', 'nezařazen')):
        return 'wait'
    return 'active'


def configure_theme(app):
    p = dict(palette(app))
    app.palette = p
    app.configure(background=p['bg'])
    s = ttk.Style(app)
    s.configure('.', font=('Calibri', 11), background=p['bg'], foreground=p['fg'])
    for name, key in {'TFrame':'bg', 'App.TFrame':'bg', 'Panel.TFrame':'panel',
                      'Card.TFrame':'card', 'Topbar.TFrame':'topbar', 'NavBar.TFrame':'navbar',
                      'SubNav.TFrame':'panel',
                      'Footer.TFrame':'bg', 'DialogShell.TFrame':'bg', 'DialogBody.TFrame':'bg',
                      'DialogHeader.TFrame':'panel'}.items():
        s.configure(name, background=p[key], bordercolor=p['border'])
    for name, bg, fg in (
        ('TLabel','bg','fg'), ('Panel.TLabel','panel','fg'), ('FilterLabel.TLabel','panel','muted'),
        ('Footer.TLabel','bg','muted'), ('FooterAccent.TLabel','bg','muted'),
        ('PageSubtitle.TLabel','bg','muted'), ('DialogTitle.TLabel','panel','fg'),
        ('DialogSubtitle.TLabel','panel','muted'), ('Title.TLabel','bg','fg'),
        ('Section.TLabel','card','fg'), ('CardTitle.TLabel','card','fg'),
        ('FocusText.TLabel','card','fg'), ('Muted.TLabel','bg','muted'),
        ('PanelMuted.TLabel','panel','muted'), ('CardMuted.TLabel','card','muted')):
        s.configure(name, background=p[bg], foreground=p[fg])
    for name in ('Topbar.TLabel', 'TopbarMuted.TLabel', 'BrandAccent.TLabel'):
        s.configure(name, background=p['topbar'], foreground=LIGHT['fg'] if name != 'TopbarMuted.TLabel' else LIGHT['muted'])
    for name in ('TLabelframe', 'TLabelframe.Label'):
        s.configure(name, background=p['panel'], foreground=p['fg'], bordercolor=p['border'])
    for name in ('TButton', 'Toolbar.TButton', 'Ghost.TButton'):
        s.configure(name, background=p['panel'], foreground=p['fg'], bordercolor=p['border'])
        s.map(name, background=[('disabled',p['head']), ('pressed',p['select']), ('active',p['head'])],
              foreground=[('disabled',p['muted'])], bordercolor=[('focus',p['accent'])])
    for name in ('Accent.TButton', 'BellAlert.TButton'):
        s.configure(name, background=p['accent'], foreground='#FFFFFF', bordercolor=p['accent'])
        s.map(name, background=[('disabled',p['head']), ('pressed',p['hover']), ('active',p['hover'])],
              foreground=[('disabled',p['muted']), ('!disabled','#FFFFFF')])
    for name in ('TopAction.TButton', 'Bell.TButton'):
        s.configure(name, background=p['topbar'], foreground=LIGHT['fg'])
        s.map(name, background=[('active',LIGHT['head'])], foreground=[('active',LIGHT['fg'])])
    for name in ('TopNav.TButton', 'TopNavActive.TButton'):
        s.configure(name, background=p['navbar'], foreground='#E1E8EE')
        s.map(name, background=[('active','#34434F')], foreground=[('active','#FFFFFF')])
    s.configure('TopNavActive.TButton', foreground='#FFFFFF')
    if not hasattr(app, '_turto_nav_underline'):
        app._turto_nav_underline = tk.PhotoImage(master=app, width=1, height=3)
        app._turto_nav_underline.put(p['accent'], to=(0,0,1,3))
        s.element_create('TurtoNav.underline', 'image', app._turto_nav_underline, sticky='ew')
    s.layout('TopNavActive.TButton', [('Button.border', {'sticky':'nswe', 'children':[
        ('TurtoNav.underline', {'side':'bottom', 'sticky':'ew'}),
        ('Button.padding', {'sticky':'nswe', 'children':[('Button.label', {'sticky':'nswe'})]})]})])
    for name in ('SubNav.TButton', 'SubNavActive.TButton'):
        s.configure(name, background=p['panel'], foreground=p['fg'], borderwidth=0,
                    padding=(12, 8), font=('Calibri', 10))
        s.map(name, background=[('active',p['head'])], foreground=[('active',p['fg'])])
    s.configure('SubNavActive.TButton', font=('Calibri', 10, 'bold'))
    s.layout('SubNavActive.TButton', s.layout('TopNavActive.TButton'))
    for name in ('FocusBadge.TLabel', 'TestMode.TLabel'):
        s.configure(name, background=p['accent'], foreground='#FFFFFF')
    search = SEARCH[p['bg'] == DARK['bg']]
    s.configure('ActiveSearch.TFrame', background=search['panel'])
    s.configure('ActiveSearch.TLabel', background=search['panel'], foreground=search['ink'])
    s.configure('SearchChip.TButton', background=search['chip'], foreground=search['ink'],
                bordercolor=search['chip'], padding=(9, 4))
    s.map('SearchChip.TButton', background=[('active',search['match']), ('pressed',search['match'])],
          foreground=[('!disabled',search['ink'])], bordercolor=[('focus',search['ink'])])
    for name, kind in (('KPIBlue.TLabel','active'), ('KPIRed.TLabel','late'),
                       ('KPIOrange.TLabel','wait'), ('KPIGreen.TLabel','done')):
        s.configure(name, background=p['card'], foreground=BADGES[p['bg']==DARK['bg']][kind][1])
    for name in ('TEntry', 'TCombobox', 'TSpinbox'):
        s.configure(name, fieldbackground=p['field'], background=p['field'], foreground=p['fg'],
                    insertcolor=p['fg'], arrowcolor=p['fg'], bordercolor=p['border'],
                    lightcolor=p['border'], darkcolor=p['border'],
                    selectbackground=p['select'], selectforeground=p['selection_fg'])
        s.map(name, fieldbackground=[('disabled',p['head']), ('readonly',p['field'])],
              foreground=[('disabled',p['muted']), ('readonly',p['fg'])],
              bordercolor=[('focus',p['accent'])])
    for name in ('TCheckbutton', 'TRadiobutton'):
        s.configure(name, background=p['panel'], foreground=p['fg'])
        s.map(name, background=[('active',p['panel'])], foreground=[('disabled',p['muted'])])
    s.configure('TNotebook', background=p['bg'], bordercolor=p['border'])
    s.configure('TNotebook.Tab', background=p['head'], foreground=p['muted'])
    s.map('TNotebook.Tab', background=[('selected',p['panel']), ('active',p['select'])],
          foreground=[('selected',p['fg']), ('active',p['fg'])])
    s.configure('Treeview', background=p['card'], fieldbackground=p['card'], foreground=p['fg'],
                bordercolor=p['border'], lightcolor=p['border'], darkcolor=p['border'],
                rowheight=30, selectbackground=p['select'], selectforeground=p['selection_fg'])
    s.configure('Treeview.Heading', background=p['head'], foreground=p['fg'], bordercolor=p['border'])
    s.map('Treeview.Heading', background=[('pressed',p['select']), ('active',p['head'])], foreground=[('active',p['fg'])])
    for axis in ('Horizontal', 'Vertical'):
        s.configure(axis+'.TScrollbar', background=p['head'], troughcolor=p['bg'], arrowcolor=p['muted'], bordercolor=p['border'])
        s.configure(axis+'.TProgressbar', background=p['accent'], troughcolor=p['head'], bordercolor=p['border'])
    for key, value in (('background',p['field']), ('foreground',p['fg']),
                       ('selectBackground',p['select']), ('selectForeground',p['selection_fg'])):
        app.option_add('*TCombobox*Listbox.'+key, value)
    for w in walk(app):
        if isinstance(w, ttk.Treeview):
            recolor_tree(w)
        elif isinstance(w, (tk.Text, tk.Listbox)):
            options = dict(bg=p['field'], fg=p['fg'], selectbackground=p['select'],
                           selectforeground=p['selection_fg'], highlightbackground=p['border'], highlightcolor=p['accent'])
            if isinstance(w, tk.Text):
                options['insertbackground'] = p['fg']
            w.configure(**options)
        elif isinstance(w, tk.Menu):
            w.configure(bg=p['panel'], fg=p['fg'], activebackground=p['select'], activeforeground=p['selection_fg'])
        elif isinstance(w, tk.Canvas) and not getattr(w, '_turto_cell_badge', False):
            w.configure(bg=p['bg'], highlightbackground=p['bg'])


def recolor_tree(tree):
    p = palette(tree)
    s = ttk.Style(tree)
    name = str(tree.cget('style') or 'Treeview')
    s.configure(name, background=p['card'], fieldbackground=p['card'], foreground=p['fg'], rowheight=30)
    s.map(name, background=[('selected',p['select'])], foreground=[('selected',p['selection_fg'])])
    for tag in ROW_TAGS:
        tree.tag_configure(tag, background='', foreground='', font='')
    decorator = getattr(tree, '_turto_cells_820', None)
    if decorator:
        decorator.schedule()


class CellBadges:
    def __init__(self, tree):
        self.tree, self.pending, self.canvases = tree, None, []
        self.last_click = None
        self.double_time, self.double_distance = 500, (4, 4)
        try:
            import ctypes
            user32 = ctypes.windll.user32
            self.double_time = user32.GetDoubleClickTime()
            self.double_distance = (user32.GetSystemMetrics(36), user32.GetSystemMetrics(37))
        except AttributeError:
            pass
        self.font = tkfont.Font(tree, family='Calibri', size=10)
        self.bold = tkfont.Font(tree, family='Calibri', size=10, weight='bold')
        self.fonts = {}
        self.rendered = []
        self.matches = []
        self.draw_count = 0
        for event in ('<Configure>', '<Map>', '<ButtonRelease-1>', '<B1-Motion>', '<<TreeviewSelect>>', '<<TreeviewOpen>>', '<<TreeviewClose>>'):
            tree.bind(event, lambda e: self.schedule(), add='+')
        tree.bind('<Destroy>', self.destroy, add='+')
        for name in ('insert', 'delete', 'detach', 'move', 'set_children', 'item', 'set', 'column', 'configure', 'tag_configure'):
            old = getattr(tree, name)
            def wrapped(*args, _name=name, _old=old, **kw):
                if _name == 'tag_configure' and args and args[0] in ROW_TAGS and kw:
                    kw.update(background='', foreground='', font='')
                result = _old(*args, **kw)
                mutate = _name in ('insert','delete','detach','move','set_children') or bool(kw)
                mutate |= _name == 'set' and len(args) >= 3
                if mutate:
                    self.schedule()
                return result
            setattr(tree, name, wrapped)
        tree.config = tree.configure
        for option in ('xscrollcommand', 'yscrollcommand'):
            original = tree.cget(option)
            def scroll(first, last, saved=original):
                if saved:
                    tree.tk.call(*tree.tk.splitlist(saved), first, last)
                self.schedule()
            tree.configure(**{option:scroll})
        recolor_tree(tree)
        self.schedule()

    def schedule(self):
        if self.pending is None and self.tree.winfo_exists():
            self.pending = self.tree.after_idle(self.draw)

    def destroy(self, event):
        if event.widget is self.tree and self.pending is not None:
            self.tree.after_cancel(self.pending)
            self.pending = None

    def canvas(self, index):
        if index == len(self.canvases):
            c = tk.Canvas(self.tree, borderwidth=0, highlightthickness=0, takefocus=0)
            c._turto_cell_badge = True
            for sequence in ('<ButtonPress-1>', '<ButtonRelease-1>', '<ButtonPress-3>', '<ButtonRelease-3>',
                             '<Motion>', '<MouseWheel>', '<Button-4>', '<Button-5>'):
                c.bind(sequence, lambda e, seq=sequence: self.forward(e, seq))
            self.canvases.append(c)
        return self.canvases[index]

    def forward(self, event, sequence):
        tree = self.tree
        options = dict(x=event.x_root-tree.winfo_rootx(), y=event.y_root-tree.winfo_rooty(),
                       state=event.state, time=event.time)
        if sequence == '<MouseWheel>':
            options['delta'] = event.delta
        if sequence == '<ButtonPress-1>':
            previous = self.last_click
            self.last_click = (event.time, options['x'], options['y'])
            if (previous is not None and 0 <= event.time-previous[0] <= self.double_time
                    and abs(options['x']-previous[1]) <= self.double_distance[0]
                    and abs(options['y']-previous[2]) <= self.double_distance[1]):
                self.last_click = None
                # Tk's native double-click matcher sees the child canvas and
                # forwarded tree events as different targets. Replay the real
                # tree's double-click bindings as one virtual event, preserving
                # bindtag order, event coordinates and each handler's break.
                scripts = [str(tree.tk.call('bind', tag, '<Double-Button-1>'))
                           for tag in tree.bindtags()]
                tree.bind('<<TurtoCellDoubleClick>>', '\n'.join(scripts))
                tree.event_generate('<<TurtoCellDoubleClick>>', **options)
                self.schedule()
                return 'break'
        tree.event_generate(sequence, **options)
        if sequence != '<Motion>':
            self.schedule()
        return 'break'

    def draw(self):
        self.pending = None
        tree = self.tree
        if not tree.winfo_exists():
            return
        self.draw_count += 1
        self.rendered = []
        self.matches = []
        if not tree.winfo_ismapped():
            for canvas in self.canvases:
                canvas.place_forget()
            return
        p = palette(tree)
        colors = BADGES[p['bg'] == DARK['bg']]
        columns = tuple(map(str, tree.cget('columns')))
        statuses = [c for c in columns if c.casefold() in STATUS_COLUMNS]
        dates = [c for c in columns if c.casefold() in DATE_COLUMNS]
        bar = getattr(tree, '_table_search', None)
        terms = tuple(bar.terms) if bar is not None else ()
        if not statuses and not dates and not terms:
            for canvas in self.canvases:
                canvas.place_forget()
            return
        # identify_row at half-row steps bounds work to the viewport, even for
        # 100,000 rows or hierarchical trees. Never enumerate all data rows.
        rows = dict.fromkeys(tree.identify_row(y) for y in range(1, tree.winfo_height(), 15))
        selected = set(tree.selection())
        style = ttk.Style(tree)
        body_font = style.lookup(str(tree.cget('style') or 'Treeview'), 'font') or 'TkDefaultFont'
        search_color = SEARCH[p['bg'] == DARK['bg']]['match']
        # Resolve visibility once. bbox() below also clips horizontally scrolled
        # columns. Only the current viewport is examined, never all data rows.
        displayed = tuple(map(str, tree.cget('displaycolumns')))
        visible = columns if displayed == ('#all',) else tuple(
            columns[int(c)] if c.isdigit() else c for c in displayed)
        candidates = visible if terms else tuple(c for c in visible if c in statuses or c in dates)
        index = 0
        for iid in rows:
            if not iid:
                continue
            values = dict(zip(columns, tree.item(iid, 'values')))
            row_tags = tree.item(iid, 'tags')
            tags = set(row_tags)
            kind = status_kind(values.get(statuses[0], '')) if statuses else ''
            row_style = {}
            if terms:
                for tag in row_tags:
                    for option in ('background', 'foreground', 'font'):
                        value = tree.tag_configure(tag, option)
                        if value and option not in row_style:
                            row_style[option] = value
            for col in candidates:
                text = str(values.get(col, ''))
                if not text.strip():
                    continue
                box = tree.bbox(iid, col)
                if not box:
                    continue
                x,y,w,h = box
                left, right = max(1,x+1), min(tree.winfo_width()-1,x+w-1)
                if right-left < 8 or y < 0:
                    continue
                spans = match_ranges(text, terms) if terms else []
                cell_kind = status_kind(text) if col in statuses else None
                if col.casefold() == 'platnost':
                    cell_kind = next((PRICE_KINDS[t] for t in tags if t in PRICE_KINDS), cell_kind)
                if col in dates:
                    parsed = None
                    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d. %m. %Y'):
                        try:
                            parsed = datetime.strptime(text.strip(), fmt).date()
                            break
                        except ValueError:
                            pass
                    tags = set(tree.item(iid, 'tags'))
                    soon = False
                    if col.casefold() == 'poptáno':
                        late = bool(tags & {'deadline_urgent', 'req_overdue_bold'})
                    elif col.casefold() == 'kdy':
                        # Notification dates have explicit business tags. Audit
                        # history also uses Kdy, but past events are not overdue.
                        late = bool(tags & {'over', 'today', 'soon'})
                    else:
                        late = parsed is not None and parsed < date.today() and kind not in ('done','cancel')
                        soon = (parsed is not None and parsed >= date.today() and kind not in ('done','cancel')
                                and bool(tags & {'v770_deadline_attention', 'status_soon', 'soon'}))
                    if late or soon:
                        cell_kind = 'wait' if soon else 'late'
                    if cell_kind and col.casefold() == 'kdy' and 'over' not in tags:
                        cell_kind = 'wait'
                if not cell_kind and not spans:
                    continue
                c = self.canvas(index)
                c.delete('all')
                c.configure(background=p['select'] if iid in selected else row_style.get('background', p['card']))
                offset = x-left
                if col in statuses:
                    bg, fg = colors[cell_kind]
                    width = min(w-10, self.font.measure(text)+30)
                    c.create_rectangle(offset+5,4,offset+5+width,h-4, fill=bg, outline=bg)
                    c.create_oval(offset+11,h//2-3,offset+17,h//2+3,fill=fg,outline=fg)
                    text_x, font = offset+23, self.font
                elif cell_kind:
                    bg, fg = colors[cell_kind]
                    c.create_rectangle(offset+3,3,offset+w-4,h-3,fill=bg,outline=bg)
                    text_x, font = offset+7, self.bold
                else:
                    spec = row_style.get('font', body_font)
                    key = str(spec)
                    if key not in self.fonts:
                        self.fonts[key] = tkfont.Font(tree, font=spec)
                    font = self.fonts[key]
                    fg = p['selection_fg'] if iid in selected else row_style.get('foreground', p['fg'])
                    anchor = str(tree.column(col, 'anchor'))
                    size = font.measure(text)
                    text_x = offset + (w-5-size if anchor == 'e' else (w-size)/2 if anchor == 'center' else 5)
                # One full text item keeps kerning, alignment and clipping intact.
                # Rectangles only decorate the actual matched character ranges.
                text_height = font.metrics('linespace')
                for start, end in spans:
                    a = text_x + font.measure(text[:start])
                    b = text_x + font.measure(text[:end])
                    c.create_rectangle(a, max(1,(h-text_height)//2), b, min(h-2,(h+text_height)//2),
                                       fill=search_color, outline='', tags='search-match')
                c.create_text(text_x,h//2,text=text,fill=fg,font=font,anchor='w')
                c.place(x=left,y=y+1,width=right-left,height=h-2)
                tk.Misc.lift(c)
                self.rendered.append((iid,col,cell_kind,box))
                if spans:
                    self.matches.append((iid, col, tuple(spans)))
                index += 1
        for canvas in self.canvases[index:]:
            canvas.place_forget()


def install_tree(tree):
    if not hasattr(tree, '_turto_cells_820'):
        tree._turto_cells_820 = CellBadges(tree)
    else:
        recolor_tree(tree)
