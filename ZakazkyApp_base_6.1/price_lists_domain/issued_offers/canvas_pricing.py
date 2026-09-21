"""Internal prices share the PDF canvas and its measured row geometry."""
from . import group_pricing, row_drag, service

FIELDS = ('purchase_unit_price', 'margin_pct', 'discount_pct')
LABELS = ('NC / MJ', 'Marže %', 'Sleva %')


def ensure_row_keys(items):
    import uuid
    for item in items:
        if not item.get('_preview_row_key'):item['_preview_row_key']=uuid.uuid4().hex


def fmt(value):
    return f'{service.number(value):,.2f}'.replace(',', ' ').replace('.', ',')


class PricingPanel:
    def __init__(self, M, editor, host=None, hidden_children=None):
        self.M, self.editor = M, editor
        self.preview = editor._v720_preview
        self.canvas = self.preview.canvas
        self.visible = True
        self.edit_widget = self.edit_window = self.edit_cell = None
        self.cells = []
        self.drag_start = self.drag_target = None
        self.dragging = False
        self._committing = False
        self.summary = M.tk.StringVar()
        self.canvas.bind('<Double-1>', self.double_click)
        self.canvas.bind('<ButtonPress-1>', self.press, add='+')
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Button-3>', self.context_menu)
        self.canvas.bind('<Escape>', lambda e:self.cancel_edit())
        self.canvas.bind('<F2>', self.keyboard_edit)

    def refresh(self):
        from .inline_pricing_workspace import _profit_totals
        values = _profit_totals(service, self.editor.items, self.editor.global_discount.get())
        self.summary.set('Nákup '+fmt(values[0])+' · Prodej '+fmt(values[1])+' · Zisk '+fmt(values[2])+' '+self.editor.currency.get())
        ensure_row_keys(self.editor.items)
        self.preview.geometry_valid = ([r.get('_preview_row_key') for r in self.editor.items] ==
            [r.get('_preview_row_key') for r in getattr(self.preview,'render_items',[])])
        self.draw()

    def sync_from_preview(self):
        pass  # There is a single scrolling surface.

    def select_from_preview(self, index):
        pass  # Selection belongs to the shared canvas.

    def draw(self):
        c, p = self.canvas, self.preview
        c.delete('internal_price'); self.cells=[]
        if not self.visible or not getattr(p, 'page_offsets', None) or not p.geometry_valid:
            self.draw_header();return
        scale = p.zoom/100
        self.left = 22 + 595.276*scale + 16
        self.width = max(88, 69*scale)
        self.right = self.left + 3*self.width
        self.draw_header()
        font=('Calibri', -max(10,round(9*scale)))
        def box(region, indices, group=False):
            if not indices: return
            for col,field in enumerate(FIELDS):
                if group and col==0: continue
                if not group and self.editor.items[indices[0]].get('row_type','product') not in {'product','service','delivery'}: continue
                x0=self.left+col*self.width; x1=x0+self.width
                y0,y1=region['y0'],region['y1']
                c.create_rectangle(x0,y0,x1,y1,fill='#e4edf3' if group else '#f5f8fb',outline='#cdd8df',tags='internal_price')
                values={self.editor.items[i].get('group_'+field) if group and self.editor.items[i].get('group_'+field) is not None else service.number(self.editor.items[i].get(field)) for i in indices}
                value=fmt(next(iter(values))) if len(values)==1 else 'Různé'
                if not group and field in group_pricing.FIELDS and self.editor.items[indices[0]].get(field.replace('_pct','_override')): value+=' *'
                c.create_text(x1-7,(y0+y1)/2,text=value,anchor='e',font=(*font,'bold') if group else font,fill='#183747',tags='internal_price')
                self.cells.append(dict(x0=x0,x1=x1,y0=y0,y1=y1,indices=indices,field=field,group=group))
        for r in getattr(p,'canvas_group_regions',[]):
            if r['kind']=='subgroup': box(r,r['indices'],True)
        for r in p.canvas_regions: box(r,[r['index']])
        p.draw_selection()

    def draw_header(self):
        header=self.preview.pricing_header
        header.delete('all')
        if not self.visible or not hasattr(self,'left'):
            header.grid_remove();return
        header.grid()
        x=self.left-self.canvas.canvasx(0)
        header.create_rectangle(0,0,max(1,header.winfo_width()),26,fill='#697078',outline='')
        header.create_text(8,13,anchor='w',text='Přetažením změníte pořadí · dvojklik upraví cenu · * vlastní marže / sleva',fill='white',font=('Calibri',10))
        for i,label in enumerate(LABELS):
            header.create_rectangle(x+i*self.width,0,x+(i+1)*self.width,26,fill='#183747',outline='#365565')
            header.create_text(x+(i+.5)*self.width,13,text=label,fill='white',font=('Calibri',10,'bold'))

    def cell_at(self, event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        return next((r for r in self.cells if r['x0']<=x<=r['x1'] and r['y0']<=y<=r['y1']),None)

    def double_click(self, event):
        if not getattr(self.preview,'geometry_valid',True):return 'break'
        self.drag_start=None
        cell=self.cell_at(event)
        if cell: self.open_editor(cell)
        else: self.preview.on_double_click(event)
        return 'break'

    def keyboard_edit(self, event=None):
        cell=next((r for r in self.cells if not r['group'] and r['indices']==[self.preview.selected_index] and r['field']=='margin_pct'),None)
        if cell: self.open_editor(cell)
        return 'break'

    def open_editor(self, cell):
        if self.editor.locked: return
        self.cancel_edit(); self.preview.close_inline()
        if not cell['group']:self.preview.select(cell['indices'][0])
        self.edit_cell=dict(cell)
        item=self.editor.items[cell['indices'][0]];field=cell['field']
        value=item.get('group_'+field) if cell['group'] else item.get(field)
        if value is None: value=item.get(field)
        self.edit_variable=self.M.tk.StringVar(value=fmt(value))
        entry=self.M.ttk.Entry(self.canvas,textvariable=self.edit_variable,justify='right')
        self.edit_widget=entry
        self.edit_window=self.canvas.create_window(cell['x0']+1,cell['y0']+1,anchor='nw',window=entry,
            width=cell['x1']-cell['x0']-2,height=max(22,cell['y1']-cell['y0']-2))
        entry.focus_set();entry.selection_range(0,'end')
        entry.bind('<Return>',lambda e:self.commit_edit())
        entry.bind('<Tab>',lambda e:self.commit_edit(next_cell=True))
        entry.bind('<Escape>',lambda e:self.cancel_edit())
        entry.bind('<FocusOut>',lambda e:self.commit_edit())

    def cancel_edit(self):
        self.drag_start=self.drag_target=None
        self.canvas.delete('drop_target')
        widget,self.edit_widget=self.edit_widget,None
        if self.edit_window is not None:self.canvas.delete(self.edit_window)
        self.edit_window=self.edit_cell=None
        if widget is not None:widget.destroy()
        return 'break'

    destroy_editor=cancel_edit

    def commit_edit(self, next_cell=False):
        cell=self.edit_cell
        if not cell or self.edit_widget is None:return 'break'
        if self._committing:return 'break'
        if self.editor.locked:return self.cancel_edit()
        self._committing=True
        try:group_pricing.apply(self.editor.items,cell['indices'],cell['field'],self.edit_variable.get(),cell['group'])
        except ValueError as exc:
            self.M.messagebox.showwarning('Cenotvorba',str(exc),parent=self.editor.win)
            if self.edit_widget:self.edit_widget.focus_set()
            return 'break'
        finally:self._committing=False
        index=self.cells.index(cell) if cell in self.cells else -1
        following=dict(self.cells[index+1]) if next_cell and 0<=index<len(self.cells)-1 else None
        self.cancel_edit();self.editor.refresh_items()
        if following:self.open_editor(following)
        return 'break'

    def context_menu(self,event):
        cell=self.cell_at(event)
        if not cell or cell['group'] or cell['field'] not in group_pricing.FIELDS or self.editor.locked:return
        menu=self.M.tk.Menu(self.canvas,tearoff=False)
        def inherit():
            if group_pricing.inherit(self.editor.items,cell['indices'][0],cell['field']):self.editor.refresh_items()
        menu.add_command(label='Převzít nastavení podskupiny',command=inherit)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def press(self,event):
        self.drag_start=None;self.dragging=False
        if self.editor.locked or self.cell_at(event) or not getattr(self.preview,'geometry_valid',True):return
        r=self.preview.region_at(self.canvas.canvasx(event.x),self.canvas.canvasy(event.y))
        if r and self.editor.items[r['index']].get('row_type','product')=='product':
            self.drag_start=(r['index'],event.x,event.y)
            self.canvas.focus_set()

    def motion(self,event):
        if self.drag_start is None:return
        source,x,y=self.drag_start
        if not self.dragging and abs(event.x-x)+abs(event.y-y)<7:return
        self.dragging=True;self.preview.close_inline()
        self.canvas.delete('drop_target')
        if event.y<30:self.canvas.yview_scroll(-1,'units')
        elif event.y>self.canvas.winfo_height()-30:self.canvas.yview_scroll(1,'units')
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        regions=self.preview.canvas_regions+getattr(self.preview,'canvas_group_regions',[])
        region=next((r for r in regions if r['x0']<=x<=r['x1'] and r['y0']<=y<=r['y1']),None)
        self.drag_target=None
        if region:
            after='index' in region and y>(region['y0']+region['y1'])/2
            self.drag_target=(region,after)
            line=region['y1'] if after else region['y0']
            self.canvas.create_line(region['x0'],line,region['x1'],line,fill='#c31f40',width=4,tags='drop_target')
        return 'break'

    def release(self,event):
        start,target=self.drag_start,self.drag_target
        self.drag_start=self.drag_target=None
        self.canvas.delete('drop_target')
        if not start or not self.dragging or not target:return
        self.dragging=False
        region,after=target;source=start[0]
        new=row_drag.target_item(self.editor.items,region)
        if new is None:return
        if row_drag.group_key(self.editor.items[source])!=row_drag.group_key(new):
            if not self.M.messagebox.askyesno('Změna skupiny položky',row_drag.warning(self.editor.items[source],new),parent=self.editor.win):return 'break'
        selected=row_drag.move(self.editor.items,source,region,after)
        self.editor.refresh_items();self.preview.select(selected)
        return 'break'
