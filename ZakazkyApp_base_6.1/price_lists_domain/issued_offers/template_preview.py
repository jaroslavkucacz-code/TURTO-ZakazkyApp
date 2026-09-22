"""Scrollable, zoomable PDF preview using the same measured output as publishing."""
import fitz
from . import subgroup_layout


class TemplatePreview:
    def __init__(self, editor, parent):
        self.editor, self.M = editor, editor.M
        M = self.M
        self.pdf = None; self.images = {}; self.offsets = []; self.result = {}; self.items = []
        editor.preview_images = self.images
        self.scale = 1.; self.fit = True; self.pending = None; self.selected = []
        toolbar = M.ttk.Frame(parent); toolbar.grid(row=1, column=0, sticky='ew', pady=4)
        self.zoom_label = M.tk.StringVar(value='Šířka stránky')
        for label, command in (('−', lambda: self.zoom(-.15)), ('+', lambda: self.zoom(.15)),
                               ('Na šířku', self.fit_width), ('‹', lambda: self.change_page(-1)), ('›', lambda: self.change_page(1))):
            M.ttk.Button(toolbar, text=label, command=command, width=10 if label=='Na šířku' else 3).pack(side='left', padx=2)
        M.ttk.Label(toolbar, textvariable=self.zoom_label).pack(side='left', padx=8)
        M.ttk.Button(toolbar, text='Otevřít PDF', command=editor.open_preview).pack(side='right')
        frame = M.ttk.Frame(parent); frame.grid(row=2, column=0, sticky='nsew')
        parent.rowconfigure(2, weight=1); parent.rowconfigure(1, weight=0)
        frame.columnconfigure(0, weight=1); frame.rowconfigure(0, weight=1)
        self.canvas = M.tk.Canvas(frame, background='#d9dfe3', highlightthickness=0, width=520, height=450)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.vertical = M.ttk.Scrollbar(frame, orient='vertical', command=self.scroll)
        self.vertical.grid(row=0, column=1, sticky='ns')
        horizontal = M.ttk.Scrollbar(frame, orient='horizontal', command=self.canvas.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=self.scrolled, xscrollcommand=horizontal.set)
        self.canvas.bind('<Configure>', lambda e: self.draw())
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<Button-4>', lambda e: self.scroll('scroll', -3, 'units'))
        self.canvas.bind('<Button-5>', lambda e: self.scroll('scroll', 3, 'units'))
        self.canvas.bind('<Button-1>', self.click)

    def load(self, path, result, items):
        if self.pdf is not None: self.pdf.close()
        self.pdf = fitz.open(stream=path.read_bytes(), filetype='pdf')
        self.result, self.items = result, items
        self.draw()
        self.select_scopes(self.selected)

    def clear(self):
        if self.pdf is not None: self.pdf.close()
        self.pdf = None; self.images = {}; self.offsets = []
        self.editor.preview_images = self.images
        if self.canvas.winfo_exists():self.canvas.delete('all')

    def draw(self):
        if self.pdf is None or not self.canvas.winfo_exists(): return
        fraction = self.canvas.yview()[0]
        if self.fit:
            self.scale = max(.25, min(2., (self.canvas.winfo_width()-32)/self.pdf[0].rect.width))
        self.zoom_label.set(f'{round(self.scale*100)} %')
        self.canvas.delete('all'); self.images = {}; self.offsets = []
        self.editor.preview_images = self.images
        y = 16
        for page in self.pdf:
            width, height = page.rect.width*self.scale, page.rect.height*self.scale
            x = max(16, (self.canvas.winfo_width()-width)/2)
            self.offsets.append((x, y, width, height))
            self.canvas.create_rectangle(x, y, x+width, y+height, fill='white', outline='#bbc3c9', tags='paper')
            y += height+20
        self.canvas.configure(scrollregion=(0, 0, max(self.canvas.winfo_width(), width+32), y))
        self.canvas.yview_moveto(fraction)
        self.highlight(); self.queue_paint()

    def queue_paint(self):
        if self.pending is None and self.pdf is not None:
            self.pending = self.canvas.after_idle(self.paint)

    def paint(self):
        self.pending = None
        if self.pdf is None: return
        from PIL import Image, ImageTk
        top = self.canvas.canvasy(0); bottom = top+self.canvas.winfo_height()
        wanted = [i for i, (_, y, _, h) in enumerate(self.offsets) if y+h>=top-40 and y<=bottom+40]
        for i in list(self.images):
            if i not in wanted:
                self.canvas.delete('page'+str(i)); del self.images[i]
        for i in wanted:
            if i in self.images: continue
            pix = self.pdf[i].get_pixmap(matrix=fitz.Matrix(self.scale, self.scale), alpha=False)
            photo = ImageTk.PhotoImage(Image.frombytes('RGB', (pix.width, pix.height), pix.samples), master=self.canvas)
            self.images[i] = photo
            self.canvas.create_image(*self.offsets[i][:2], image=photo, anchor='nw', tags='page'+str(i))
            self.canvas.tag_lower('page'+str(i)); self.canvas.tag_lower('paper')

    def scrolled(self, first, last):
        self.vertical.set(first, last); self.queue_paint()

    def scroll(self, *args):
        self.canvas.yview(*args); self.queue_paint()
        return 'break'

    def wheel(self, event):
        if event.state & 4:
            self.zoom(.1 if event.delta>0 else -.1)
        else:
            self.scroll('scroll', -3 if event.delta>0 else 3, 'units')
        return 'break'

    def zoom(self, delta):
        self.fit = False; self.scale = max(.25, min(2.5, self.scale+delta)); self.draw()

    def fit_width(self):
        self.fit = True; self.draw()

    def page_index(self):
        y = self.canvas.canvasy(0)+30
        return next((i for i, (_, top, _, h) in enumerate(self.offsets) if top+h>y), 0)

    def change_page(self, delta):
        if not self.offsets: return
        index = max(0, min(len(self.offsets)-1, self.page_index()+delta))
        height = float(self.canvas.cget('scrollregion').split()[3])
        self.canvas.yview_moveto(max(0, self.offsets[index][1]-10)/height)

    def record(self, region):
        index = region.get('index')
        if index is None:
            index = next(iter(region.get('indices', [])), None)
        return self.items[index] if index is not None and 0<=index<len(self.items) else None

    def selected_region(self, region):
        item = self.record(region)
        if item is None: return False
        value = subgroup_layout.scope(item)
        return any(subgroup_layout.key(s)==subgroup_layout.key(value) or subgroup_layout.names(s)==subgroup_layout.names(value) for s in self.selected)

    def highlight(self):
        self.canvas.delete('selection')
        for region in self.result.get('group_regions', []) + self.result.get('table_regions', []):
            if region.get('kind') == 'category' or not self.selected_region(region): continue
            if region['page'] >= len(self.offsets): continue
            x, y, _, _ = self.offsets[region['page']]
            self.canvas.create_rectangle(x+region['x0']*self.scale, y+region['y0']*self.scale,
                                         x+region['x1']*self.scale, y+region['y1']*self.scale,
                                         outline='#138dcc', width=2, tags='selection')

    def select_scopes(self, values):
        self.selected = list(values); self.highlight()
        region = next((r for r in self.result.get('group_regions', []) if r.get('kind')=='subgroup' and self.selected_region(r)), None)
        if region is not None and region['page'] < len(self.offsets):
            y = self.offsets[region['page']][1]+region['y0']*self.scale
            top = self.canvas.canvasy(0)
            if y<top or y>top+self.canvas.winfo_height()-80:
                height = float(self.canvas.cget('scrollregion').split()[3])
                self.canvas.yview_moveto(max(0, y-30)/height)

    def click(self, event):
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for index, (left, top, width, height) in enumerate(self.offsets):
            if not (left<=x<=left+width and top<=y<=top+height): continue
            px, py = (x-left)/self.scale, (y-top)/self.scale
            for region in self.result.get('group_regions', []) + self.result.get('table_regions', []) + self.result.get('regions', []):
                if region.get('kind')=='category': continue
                if region['page']==index and region['x0']<=px<=region['x1'] and region['y0']<=py<=region['y1']:
                    item = self.record(region)
                    if item is not None: self.editor.subgroups.select_scope(item, bool(event.state & 4))
                    return 'break'

    def close(self):
        if self.pending is not None:
            try:self.canvas.after_cancel(self.pending)
            except Exception:pass
            self.pending = None
        self.clear()
