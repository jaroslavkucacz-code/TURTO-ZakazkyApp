"""Portfolio edits use the same people records as the directory."""
from contextlib import closing
from . import user_access as access, catalog_selection

FIELDS = {'Společnost / kontakt':'name','Telefon':'phone','E-mail':'email','Funkce':'role'}


def display_value(column, value):
    value=str(value or '')
    return '\u2003\u2003↳  '+value if column=='Společnost / kontakt' else value


def rows(M, company_id):
    access.require(M,'people',write=False)
    with closing(M.db()) as con:
        return [dict(r) for r in con.execute('SELECT * FROM people WHERE company_id=? AND active=1 ORDER BY name COLLATE CZECH,id',(company_id,))]


def grouped(M, company_ids):
    access.require(M,'people',write=False)
    out={};ids=list(company_ids)
    with closing(M.db()) as con:
        for offset in range(0,len(ids),400):
            chunk=ids[offset:offset+400]
            for r in con.execute(f"SELECT * FROM people WHERE active=1 AND company_id IN ({','.join('?' for _ in chunk)}) ORDER BY name COLLATE CZECH,id",chunk):
                out.setdefault(r['company_id'],[]).append(dict(r))
    return out


def save(M, company_id, pid, field, value, original):
    access.require(M,'portfolio',write=False);access.require(M,'people')
    if field not in FIELDS.values():raise ValueError('Toto pole nelze upravit v řádku.')
    value=str(value or '').strip()
    if field=='name' and not value:raise ValueError('Vyplňte jméno kontaktní osoby.')
    if field=='email' and not value and original.get('email'):raise ValueError('Vyplňte e-mail kontaktní osoby.')
    with closing(M.db()) as con,con:
        con.execute('BEGIN IMMEDIATE')
        old=con.execute('SELECT * FROM people WHERE id=? AND company_id=? AND active=1',(pid,company_id)).fetchone()
        if not old or any(old[k]!=original[k] for k in ('name','phone','email','role','company_id','active')):
            raise ValueError('Kontakt byl mezitím změněn, přesunut nebo deaktivován. Obnovte portfolio.')
        if field=='role':value=catalog_selection.existing_name(con,'person_roles',value,(old['role'],))
        if field=='email' and value and con.execute('SELECT 1 FROM people WHERE lower(trim(email))=lower(?) AND id<>?',(value,pid)).fetchone():
            raise ValueError('Tento e-mail už má jiná osoba v adresáři.')
        con.execute(f'UPDATE people SET {field}=? WHERE id=?',(value,pid))


class Editor:
    def __init__(self, workspace):
        self.ws=workspace;self.M=workspace.M;self.tree=workspace.tree;self.entry=None;self.busy=False
        self.tree.bind('<Double-1>',self.double_click)
        self.tree.bind('<F2>',lambda e:self.begin_selected())
        self.tree.bind('<Configure>',lambda e:self.reposition(),add='+')
        for option in ('xscrollcommand','yscrollcommand'):
            previous=self.tree.cget(option)
            def scrolled(first,last,callback=previous):
                if callback:self.tree.tk.call(*self.tree.tk.splitlist(callback),first,last)
                if self.entry:self.tree.after_idle(self.reposition)
            self.tree.configure(**{option:scrolled})

    def double_click(self,event):
        iid=self.tree.identify_row(event.y)
        region=self.tree.identify_region(event.x,event.y)
        if region not in ('cell','tree') or not iid:return
        # The first press already toggled the native indicator. Never open a
        # detail or let the Treeview double-click class binding toggle it again.
        if 'indicator' not in self.tree.identify_element(event.x,event.y):
            self.ws.open_detail(iid)
        return 'break'

    def begin_selected(self):
        selected=self.tree.selection()
        if selected:self.begin(selected[0],'Společnost / kontakt')
        return 'break'

    def begin(self,iid,column):
        if not iid.startswith('p') or column not in FIELDS or not self.commit():return
        if not access.allowed(self.M,self.ws.app,'people'):return
        pid=int(iid[1:]);parent=self.tree.parent(iid);cid=int(parent[1:])
        originals={r['id']:r for r in rows(self.M,cid)}
        if pid not in originals:self.ws.refresh();return
        self.original=originals[pid];self.pid=pid;self.cid=cid;self.iid=iid;self.column=column
        session=getattr(self.M,'_user_access_session',None)
        self.identity=(session.user_id if session else None,str(self.M.DB))
        self.variable=self.M.tk.StringVar(master=self.tree,value=self.original[FIELDS[column]] or '')
        if column=='Funkce':
            with closing(self.M.db()) as con:roles=[r[0] for r in con.execute('SELECT name FROM person_roles WHERE active=1 ORDER BY name COLLATE CZECH')]
            self.entry=self.M.ttk.Combobox(self.tree,textvariable=self.variable,values=('',*roles),state='readonly')
        else:self.entry=self.M.ttk.Entry(self.tree,textvariable=self.variable)
        self.entry._turto_own_input_navigation=True
        self.tree.see(iid);self.reposition();self.entry.focus_set()
        if column!='Funkce':self.entry.selection_range(0,'end')
        self.entry.bind('<Return>',lambda e:self.finish())
        self.entry.bind('<Escape>',lambda e:self.cancel())
        self.entry.bind('<Tab>',lambda e:self.next_cell())
        self.entry.bind('<Shift-Tab>',lambda e:self.next_cell(-1))
        self.entry.bind('<ISO_Left_Tab>',lambda e:self.next_cell(-1))
        self.entry.bind('<FocusOut>',lambda e:self.tree.after_idle(self.focus_out))

    def reposition(self):
        if not self.entry:return
        box=self.tree.bbox(self.iid,self.column)
        if box:self.entry.place(x=box[0],y=box[1],width=box[2],height=box[3])
        else:self.entry.place_forget()

    def cancel(self):
        widget=self.entry;self.entry=None
        if widget:widget.destroy()
        return 'break'

    def commit(self):
        if not self.entry or self.busy:return True
        session=access.refresh_session(self.M)
        if self.identity!=(session.user_id if session else None,str(self.M.DB)):
            self.cancel();return False
        self.busy=True
        try:
            save(self.M,self.cid,self.pid,FIELDS[self.column],self.variable.get(),self.original)
            self.tree.set(self.iid,self.column,display_value(self.column,self.variable.get().strip()))
            self.cancel()
            self.ws.app.refresh_people()
            return True
        except (ValueError,self.M.sqlite3.Error) as exc:
            self.M.messagebox.showwarning('Kontakt',str(exc),parent=self.ws.app)
            if self.entry:self.entry.focus_set()
            return False
        finally:self.busy=False

    def focus_out(self):
        if self.entry and self.tree.focus_get() is not self.entry:
            # A readonly combo's popdown is a separate native window.
            if self.column=='Funkce' and self.entry.tk.call('ttk::combobox::PopdownWindow',self.entry):
                popup=self.entry.tk.call('ttk::combobox::PopdownWindow',self.entry)
                if self.entry.tk.call('winfo','ismapped',popup):return
            self.commit()

    def finish(self):
        if self.commit():self.tree.focus_set()
        return 'break'

    def next_cell(self,step=1):
        iid,column=self.iid,self.column
        if self.commit():
            fields=list(FIELDS);self.begin(iid,fields[(fields.index(column)+step)%len(fields)])
        return 'break'
