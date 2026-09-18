"""Responsive Tk charts. No Matplotlib, Pillow or native graphics extensions."""
from __future__ import annotations
import math
import tkinter as tk
from tkinter import font as tkfont
from .constants import COLORS
from .chart_geometry import axis, grouped, series_value, number, money as fmt_money, percent as fmt_pct, count

PALETTE=(COLORS['teal'],COLORS['amber'],COLORS['blue'],'#AB96DF','#D693B3','#96C5A4','#8193A9','#BF9780')
SPECIAL_COLORS={'Milan':COLORS['teal'],'Honza':COLORS['blue'],'Jirka':COLORS['amber'],'Nezařazené':'#8193A9'}
MIN_DONUT_DEGREES=0.5

def _metric_color(key):
    return {'revenue':COLORS['teal'],'profit':COLORS['amber'],'margin':COLORS['blue'],'count':COLORS['blue']}.get(key,COLORS['text'])

def _display_colors(items):
    # Barvy se přidělují jen právě zobrazeným kategoriím. TOP položky tak
    # nemohou dostat stejnou barvu kvůli cyklování palety přes skryté řádky.
    result={};used=set();palette_index=0
    for item in items:
        label=str(item.get('label') or 'Bez názvu')
        if label in SPECIAL_COLORS:
            color=SPECIAL_COLORS[label]
        elif label.startswith('Nezařazené') or label.startswith('Ostatní'):
            color='#8193A9'
        else:
            color=None
            for _ in range(len(PALETTE)):
                candidate=PALETTE[palette_index%len(PALETTE)];palette_index+=1
                if candidate not in used:
                    color=candidate;break
            if color is None:color=PALETTE[palette_index%len(PALETTE)]
        result[label]=color;used.add(color)
    return result


def _fit(font,text,width):
    text=str(text).replace('\n',' ')
    if font.measure(text)<=width:return text
    lo,hi=0,len(text)
    while lo<hi:
        mid=(lo+hi+1)//2
        if font.measure(text[:mid]+'…')<=width:lo=mid
        else:hi=mid-1
    return text[:lo]+'…' if width>font.measure('…') else ''


class _CanvasFrame(tk.Frame):
    def __init__(self,master):
        super().__init__(master,bg=COLORS['panel'])
        self._pending=None
        self._fonts={}
        self.bind('<Destroy>',self._destroyed,add='+')

    def _font(self,size=9,bold=False):
        key=(size,bold)
        if key not in self._fonts:self._fonts[key]=tkfont.Font(self,family='Calibri',size=size,weight='bold' if bold else 'normal')
        return self._fonts[key]

    def _label(self,text):
        label=tk.Label(self,text=text,bg=COLORS['panel'],fg=COLORS['muted'],justify='left',anchor='w',font=('Calibri',9))
        label.pack(fill='x',pady=(0,6))
        label.bind('<Configure>',lambda e:label.configure(wraplength=max(40,e.width-4)))
        return label

    def _controls(self,items):
        bar=tk.Frame(self,bg=COLORS['panel']);bar.pack(fill='x',pady=(0,6))
        buttons={}
        for key,label,command in items:
            b=tk.Button(bar,text=label,command=command,font=('Calibri',9,'bold'),padx=9,pady=5,relief='flat',bd=0,takefocus=True)
            b.bind('<Return>',lambda e,button=b:button.invoke())
            buttons[key]=b
        state=[None]
        def arrange(event=None):
            width=max(1,bar.winfo_width());x=0;y=0;positions=[]
            height=max([b.winfo_reqheight() for b in buttons.values()]+[30])+4
            for key,label,_ in items:
                b=buttons[key]
                needed=max(b.winfo_reqwidth()+5,self._font(9,True).measure('✓ '+label)+26)
                if x and x+needed>width:x=0;y+=height
                positions.append((x,y,needed-5,height-4));x+=needed
            signature=(tuple(positions),height)
            if signature==state[0]:return
            state[0]=signature
            for b,(x,y,w,h) in zip(buttons.values(),positions):b.place(x=x,y=y,width=w,height=h)
            bar.configure(height=y+height)
        bar.bind('<Configure>',arrange)
        bar._chart_arrange=arrange
        arrange()
        return buttons

    def _style_button(self,button,label,active,available=True,color=None):
        button.configure(text=('✓ ' if active and available else '')+label,
            state='normal' if available else 'disabled',bg=COLORS['panel_alt'] if active else COLORS['panel_soft'],
            fg=(color or COLORS['teal']) if active else COLORS['text'],disabledforeground=COLORS['muted'],
            activebackground=COLORS['border'],activeforeground=COLORS['text'])
        button.master._chart_arrange()

    def _canvas(self,height):
        self.canvas=tk.Canvas(self,bg=COLORS['panel'],highlightthickness=0,bd=0,height=height)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self._schedule)
        self._schedule()

    def _schedule(self,event=None):
        if self._pending is None:self._pending=self.after_idle(self._scheduled_draw)

    def _scheduled_draw(self):
        self._pending=None
        if self.winfo_exists():self._draw()

    def _destroyed(self,event):
        if event.widget is self and self._pending is not None:
            try:self.after_cancel(self._pending)
            except tk.TclError:pass
            self._pending=None

    def _text(self,x,y,text,*,width=None,size=9,bold=False,color=None,anchor='w',tag='labels'):
        font=self._font(size,bold)
        text=_fit(font,text,width) if width is not None else str(text)
        return self.canvas.create_text(x,y,text=text,font=font,fill=color or COLORS['text'],anchor=anchor,tags=(tag,))

    def _tooltip(self,text,x,y):
        c=self.canvas;c.delete('tooltip');w=c.winfo_width();h=c.winfo_height()
        font=self._font(9)
        width=max(30,min(w-28,max(font.measure(s) for s in text.split('\n'))))
        item=c.create_text(14,10,text=text,anchor='nw',font=font,width=width,fill=COLORS['text'],tags=('tooltip',))
        box=c.bbox(item)
        # Extremely long names must not push a tooltip outside the chart.
        remaining=text
        while box and box[3]-box[1]+18>h-4 and len(remaining)>8:
            remaining=remaining[:max(8,int(len(remaining)*.85))].rstrip()
            c.itemconfigure(item,text=remaining+'…');box=c.bbox(item)
        tw,th=box[2]-box[0]+24,box[3]-box[1]+18
        x=max(2,min(x,w-tw-2));y=max(2,min(y,h-th-2))
        c.move(item,x+12-box[0],y+9-box[1])
        rect=c.create_rectangle(x,y,x+tw,y+th,fill=COLORS['panel_soft'],outline=COLORS['border'],tags=('tooltip',))
        c.tag_lower(rect,item)

    def _notify(self,callback,data):
        if callback:
            try:callback(data)
            except Exception:
                import sys
                self._root().report_callback_exception(*sys.exc_info())


class BusinessChart(_CanvasFrame):
    SERIES=(('revenue','Obrat',COLORS['teal']),('profit','Zisk',COLORS['amber']),('margin','Marže %',COLORS['blue']))
    VIEWS=(('combined','Kombinovaný'),('lines','Čáry'),('bars','Sloupce'))

    def __init__(self,master,data,*,subtitle='Částky vlevo · marže na pravé ose',show_mode_switch=True,
                 trim_trailing_empty=False,on_period_click=None,height=290,initial_enabled=('revenue','profit','margin'),
                 preferences=None,on_state_change=None):
        super().__init__(master)
        self._all_data=[dict(x) for x in data];self._data=self._all_data[:]
        self.SERIES=(('revenue','Obrat',COLORS['teal']),('profit','Zisk',COLORS['amber']),('margin','Marže %',COLORS['blue']))
        for row in self._data:
            if row.get('profit_complete') is False:row['margin']=None
        if trim_trailing_empty:
            while self._data and not (self._data[-1].get('has_data') or any((series_value(self._data[-1],k) or 0)!=0 for k in ('revenue','profit'))):self._data.pop()
        prefs=preferences if isinstance(preferences,dict) else {}
        chosen=prefs.get('enabled',initial_enabled)
        if not isinstance(chosen,(list,tuple)):chosen=initial_enabled
        self._available={k:any(series_value(r,k) is not None for r in self._data) for k,_,_ in self.SERIES}
        self._enabled={k:k in chosen and self._available[k] for k,_,_ in self.SERIES}
        if chosen and not any(self._enabled.values()):
            first=next((k for k,_,_ in self.SERIES if self._available[k]),None)
            if first:self._enabled[first]=True
        self.view=prefs.get('view','combined')
        if self.view not in dict(self.VIEWS):self.view='combined'
        self._on_state_change=on_state_change
        self._hover_index=None;self._centers=[];self._plot_bounds=(0,0,0,0);self._on_period_click=on_period_click
        self._label(subtitle)
        self._buttons={};self.view_buttons={}
        if show_mode_switch:
            self._buttons=self._controls([(k,label,lambda key=k:self.toggle(key)) for k,label,_ in self.SERIES])
            self.view_buttons=self._controls([(k,label,lambda key=k:self.set_view(key)) for k,label in self.VIEWS])
        self.status=self._label('')
        self._refresh_buttons();self._canvas(height)
        self.canvas.bind('<Motion>',self._motion);self.canvas.bind('<Leave>',self._leave);self.canvas.bind('<Button-1>',self._click)

    def state(self):return {'view':self.view,'enabled':[k for k,enabled in self._enabled.items() if enabled]}

    def _refresh_buttons(self):
        for key,label,color in self.SERIES:
            if key in self._buttons:
                self._style_button(self._buttons[key],label+(' · bez dat' if not self._available[key] else ''),self._enabled[key],self._available[key],color)
        for key,label in self.VIEWS:
            if key in self.view_buttons:self._style_button(self.view_buttons[key],label,key==self.view,any(self._available.values()))
        unavailable=[label for k,label,_ in self.SERIES if not self._available[k]]
        note='Ukazatele lze zapínat samostatně i společně.'
        if not any(self._available.values()):note='Pro toto období nejsou dostupné hodnoty.'
        elif unavailable:
            note='Bez podkladů: '+', '.join(unavailable)+'.'
            if not self._available['margin']:note+=' Marže vyžaduje obrat a úplný zisk.'
        if any(self._available.values()) and not any(self._enabled.values()):note='Vyberte alespoň jeden ukazatel nad grafem.'
        self.status.configure(text=dict(self.VIEWS)[self.view]+' · '+note)

    def toggle(self,key):
        if key not in self._enabled or not self._available[key]:return
        self._enabled[key]=not self._enabled[key]
        self._changed()

    def set_view(self,key):
        if key not in dict(self.VIEWS) or not any(self._available.values()):return
        self.view=key;self._changed()

    def _changed(self):
        self._hover_index=None;self._refresh_buttons();self._draw()
        self._notify(self._on_state_change,self.state())

    def _draw(self,event=None):
        c=self.canvas;c.delete('all');w=c.winfo_width();h=c.winfo_height();self._centers=[];self._plot_bounds=(0,0,0,0)
        if w<150 or h<125:return
        if not self._data or not any(self._available.values()):
            self._text(w/2,h/2,'Pro vybrané období nejsou data.',width=w-16,anchor='center',color=COLORS['muted']);return
        if not any(self._enabled.values()):
            self._text(w/2,h/2,'Zapněte Obrat, Zisk nebo Marži nad grafem.',width=w-16,anchor='center',color=COLORS['muted']);return
        mo=self._enabled['revenue'] or self._enabled['profit'];po=self._enabled['margin']
        ma=axis([series_value(r,k) for r in self._data for k in ('revenue','profit') if self._enabled[k]])
        pa=axis([series_value(r,'margin') for r in self._data],True)
        f=self._font(9)
        left=max(56,max(f.measure(ma.label(v)) for v in ma.ticks())+16) if mo else 12
        right=max(68,max(f.measure(pa.label(v)) for v in pa.ticks())+16) if po else 12
        fh=f.metrics('linespace');nh=self._font(8).metrics('linespace')
        top=max(40,fh+18);bottom=h-(2*fh+nh+15);xr=w-right
        if xr-left<55 or bottom-top<40:return
        self._plot_bounds=(left,top,xr,bottom);self._axes=(ma,pa)
        slot=(xr-left)/len(self._data);self._centers=[left+(i+.5)*slot for i in range(len(self._data))]
        if self._hover_index is not None and self._hover_index<len(self._data):
            cx=self._centers[self._hover_index]
            c.create_rectangle(cx-slot*.48,top,cx+slot*.48,bottom,fill=COLORS['panel_alt'],outline='')
        grid=ma if mo else pa
        for v in grid.ticks():
            y=grid.position(v,top,bottom)
            c.create_line(left,y,xr,y,fill=COLORS['grid'] if v==0 else '#253348',width=1)
        if mo:
            self._text(left-8,12,ma.unit,anchor='e',size=8,bold=True,color=COLORS['muted'])
            for v in ma.ticks():self._text(left-8,ma.position(v,top,bottom),ma.label(v),anchor='e',color=COLORS['muted'])
        if po:
            self._text(xr+8,12,'Marže %',size=8,bold=True,color=COLORS['blue'])
            for v in pa.ticks():self._text(xr+8,pa.position(v,top,bottom),pa.label(v),color=COLORS['blue'])
        # Kč use the left axis; percentages always retain their own right axis.
        bar_keys=[k for k in ('revenue','profit') if self._enabled[k] and (self.view=='bars' or (self.view=='combined' and k=='revenue'))]
        if self.view=='bars' and po and not mo:bar_keys=['margin']
        group_width=min(70,slot*.72);bw=group_width/max(1,len(bar_keys))
        for bindex,key in enumerate(bar_keys):
            scale=pa if key=='margin' else ma;zero=scale.position(0,top,bottom);color=_metric_color(key)
            for cx,row in zip(self._centers,self._data):
                v=series_value(row,key)
                if v is None:continue
                x=cx-group_width/2+(bindex+.5)*bw;y=scale.position(v,top,bottom)
                if abs(y-zero)<1:c.create_line(x-bw*.42,zero,x+bw*.42,zero,fill=color,width=2,tags=('series',key))
                else:c.create_rectangle(x-bw*.42,min(y,zero),x+bw*.42,max(y,zero),fill=color,outline='',tags=('series',key))
        for key,_,color in self.SERIES:
            if not self._enabled[key] or key in bar_keys:continue
            scale=pa if key=='margin' else ma
            segments=[];points=[]
            for cx,row in zip(self._centers,self._data):
                v=series_value(row,key)
                if v is None:
                    if points:segments.append(points);points=[]
                else:points.extend((cx,scale.position(v,top,bottom)))
            if points:segments.append(points)
            for pts in segments:
                if len(pts)>=4:c.create_line(*pts,fill=color,width=2.5,dash=(5,3) if key=='margin' else (),joinstyle='round',capstyle='round',tags=('series',key))
                for i in range(0,len(pts),2):c.create_oval(pts[i]-3,pts[i+1]-3,pts[i]+3,pts[i+1]+3,fill=color,outline=COLORS['panel'],tags=('series',key))
        last_end=-100
        for cx,row in zip(self._centers,self._data):
            label=str(row.get('label',''));width=f.measure(label)
            if cx-width/2>=last_end+9 and cx+width/2<=w-3:
                self._text(cx,bottom+fh+5,label,anchor='center',color=COLORS['muted']);last_end=cx+width/2
        note='Chybějící data = mezera, nikoli nula.'
        if any(r.get('profit_complete') is False and r.get('profit_available') for r in self._data):note='* Zisk je částečný; marže jen s úplným podkladem.'
        if self.view=='bars' and po and mo:note='Částky ve sloupcích · marže čárou na pravé ose. '+note
        self._text(left,h-nh/2-3,note,width=w-left-3,size=8,color=COLORS['muted'])
        if self._hover_index is not None and self._hover_index<len(self._data):self._draw_tooltip(self._hover_index)

    def _draw_tooltip(self,index):
        r=self._data[index];lines=[str(r.get('full_label') or r.get('period') or r.get('label') or '')]
        for k,label,_ in self.SERIES:
            if self._enabled[k]:
                v=series_value(r,k);value=fmt_pct(v) if k=='margin' else fmt_money(v)
                lines.append(label+': '+value+(' *' if k=='profit' and r.get('profit_complete') is False and v is not None else ''))
        if r.get('source')=='legacy':lines.append('Zisk: historický měsíční souhrn')
        self._tooltip('\n'.join(lines),self._centers[index]+12,self._plot_bounds[1]+10)

    def _index_at(self,event):
        l,t,r,b=self._plot_bounds
        if not self._centers or not(l<=event.x<=r and t<=event.y<=b):return None
        return min(range(len(self._centers)),key=lambda i:abs(self._centers[i]-event.x))

    def _motion(self,event):
        index=self._index_at(event)
        if index!=self._hover_index:self._hover_index=index;self._draw()
        self.canvas.configure(cursor='hand2' if index is not None and self._on_period_click else 'arrow')

    def _leave(self,event=None):
        if self._hover_index is not None:self._hover_index=None;self._draw()

    def _click(self,event):
        index=self._index_at(event)
        if index is not None:self._notify(self._on_period_click,self._data[index])


class ShareChart(_CanvasFrame):
    PALETTE=PALETTE
    VIEWS=(('compare','Pruhy'),('shares','Prstenec'),('stacked','Podíly 100 %'))

    def __init__(self,master,rows,*,metrics,initial_metric,title_note='',max_items=6,
                 exclude_negative_from_shares=False,on_item_click=None,height=245,preferences=None,on_state_change=None):
        super().__init__(master)
        self.rows=[dict(x) for x in rows];self.metrics=metrics;self.max_items=max_items
        self._colors={};self._on_state_change=on_state_change
        prefs=preferences if isinstance(preferences,dict) else {}
        wanted=prefs.get('metric',initial_metric)
        keys=[x[0] for x in metrics]
        self.metric=wanted if wanted in keys and self._metric_available(wanted) else next((k for k in keys if self._metric_available(k)),keys[0])
        self.view=prefs.get('view','shares')
        if self.view not in dict(self.VIEWS):self.view='shares'
        if not self._share_available():self.view='compare'
        self.on_item_click=on_item_click;self._note=title_note;self._hit_regions=[];self._wedges=[]
        self.metric_buttons=self._controls([(key,label,lambda k=key:self.set_metric(k)) for key,label,_ in metrics])
        self.view_buttons=self._controls([(key,label,lambda k=key:self.set_view(k)) for key,label in self.VIEWS])
        self.status=self._label('');self._refresh_buttons();self._canvas(height)
        self.canvas.bind('<Button-1>',self._click);self.canvas.bind('<Motion>',self._motion);self.canvas.bind('<Leave>',lambda e:self.canvas.delete('tooltip'))

    def _metric_available(self,key):return any(series_value(r,key) is not None for r in self.rows)
    def _share_available(self):
        vals=[series_value(r,self.metric) for r in self.rows]
        vals=[v for v in vals if v is not None]
        return bool(vals) and min(vals)>=0 and sum(vals)>0
    def state(self):return {'metric':self.metric,'view':self.view}
    def set_metric(self,key):
        if any(x[0]==key for x in self.metrics) and self._metric_available(key):
            self.metric=key
            if self.view!='compare' and not self._share_available():self.view='compare'
            self._changed()
    def set_view(self,key):
        if key not in dict(self.VIEWS) or not self._metric_available(self.metric):return
        if key!='compare' and not self._share_available():return
        self.view=key;self._changed()
    def _changed(self):
        self._refresh_buttons();self._draw();self._notify(self._on_state_change,self.state())
    def _refresh_buttons(self):
        for key,label,_ in self.metrics:self._style_button(self.metric_buttons[key],label+(' · bez dat' if not self._metric_available(key) else ''),key==self.metric,self._metric_available(key),_metric_color(key))
        for key,label in self.VIEWS:self._style_button(self.view_buttons[key],label,key==self.view,self._metric_available(self.metric) and (key=='compare' or self._share_available()))
        unavailable=[label for k,label,_ in self.metrics if not self._metric_available(k)]
        messages=[]
        if unavailable:messages.append('Bez podkladů: '+', '.join(unavailable)+'.')
        if self._metric_available(self.metric) and not self._share_available():
            negative=any((series_value(r,self.metric) or 0)<0 for r in self.rows)
            messages.append('Záporné hodnoty zobrazují pruhy; procentní podíly nejsou vhodné.' if negative else 'Součet je nulový; procentní podíly nelze vypočítat.')
        if any(r.get('profit_complete') is False and r.get('profit_available') for r in self.rows) and self.metric=='profit':messages.append('Zisk je pouze z dostupných podkladů.')
        if not messages:messages.append('Najeďte na hodnotu pro detail'+('; kliknutím otevřete položku.' if self.on_item_click else '.'))
        self.status.configure(text=dict(self.VIEWS)[self.view]+' · '+' '.join(messages))
    def _formatter(self):return {'count':count,'pct':fmt_pct}.get(next((x[2] for x in self.metrics if x[0]==self.metric),'money'),fmt_money)

    def _draw(self,event=None):
        c=self.canvas;c.delete('all');self._hit_regions=[];self._wedges=[]
        w=c.winfo_width();h=c.winfo_height()
        if w<180 or h<100:return
        items,missing,negative=grouped(self.rows,self.metric,self.max_items)
        if not items:
            self._text(w/2,h/2,'Pro zvolený ukazatel nejsou data.',width=w-15,anchor='center',color=COLORS['muted']);return
        self._colors=_display_colors(items)
        note=self._note
        if missing:note+=f' Bez hodnoty: {missing}.'
        font=self._font(8)
        probe=c.create_text(4,0,text=note,anchor='nw',width=w-8,font=font)
        box=c.bbox(probe);nh=(box[3]-box[1]+14) if note else 8;c.delete(probe)
        rowh=max(28,self._font(9).metrics('linespace')+12)
        total=sum(x['value'] for x in items);fmt=self._formatter()
        share=self._share_available();view=self.view if share else 'compare'
        top=0;start_x=10;donut=view=='shares'
        # Narrow charts retain the requested type; the legend moves below the ring.
        wide=w>=650
        ring_size=176
        if donut:
            if wide:start_x=ring_size+38
            else:top=ring_size+20
        if view=='stacked':top=64
        required=max(ring_size+12 if donut and wide else 0,top+rowh*len(items))+nh+8
        if abs(int(float(c.cget('height')))-required)>2:c.configure(height=required)
        if note:c.create_text(4,h-nh+4,text=note,width=w-8,font=font,anchor='nw',fill=COLORS['muted'],tags=('footnote',))
        if donut:
            size=ring_size;x0=10 if wide else (w-size)/2;y0=4
            cx=x0+size/2;cy=y0+size/2;start=90
            for item in items:
                if item['value']<=0:continue
                degrees=359.99*item['value']/total;extent=-degrees
                if degrees>=MIN_DONUT_DEGREES:
                    c.create_arc(x0,y0,x0+size,y0+size,start=start,extent=extent,fill=self._colors[item['label']],outline=COLORS['panel'],width=2,tags=('segment','donut'))
                    self._wedges.append((cx,cy,size/2,size*.31,start,extent,item,total))
                start+=extent
            hole=size*.62;c.create_oval(cx-hole/2,cy-hole/2,cx+hole/2,cy+hole/2,fill=COLORS['panel'],outline='')
            self._text(cx,cy-12,'CELKEM',anchor='center',size=8,color=COLORS['muted'])
            self._text(cx,cy+10,fmt(total),width=hole-8,anchor='center',size=10,bold=True)
        elif view=='stacked':
            left=12;right=w-12;cursor=left
            self._text(left,8,'Rozdělení celku',size=8,color=COLORS['muted'])
            self._text(right,8,'100 %',size=8,color=COLORS['muted'],anchor='e')
            for item in items:
                if item['value']<=0:continue
                end=cursor+item['value']/total*(right-left)
                c.create_rectangle(cursor,23,end,49,fill=self._colors[item['label']],outline=COLORS['panel'],tags=('segment','stacked'))
                self._hit_regions.append((cursor,23,end,49,item,total));cursor=end
        percent_on=view!='compare';pw=72 if percent_on else 0
        value_width=max(82,max(self._font(9,True).measure(fmt(x['value'])) for x in items)+14)
        value_right=w-pw-12
        bar_right=value_right-value_width-10
        label_need=max(self._font(9).measure(str(x['label'])) for x in items)+24
        label_width=max(50,min(330,w*.33,label_need))
        if view=='compare':label_width=min(label_width,max(40,bar_right-start_x-75))
        else:label_width=max(40,bar_right-start_x)
        bar_left=start_x+label_width+14
        lo=min([0]+[x['value'] for x in items]);hi=max([0]+[x['value'] for x in items]);span=hi-lo or 1
        zero=bar_left+(0-lo)/span*max(0,bar_right-bar_left)
        for i,item in enumerate(items):
            y=top+rowh*(i+.5);col=COLORS['red'] if item['value']<0 else self._colors[item['label']]
            c.create_oval(start_x,y-3,start_x+6,y+3,fill=col,outline='')
            self._text(start_x+13,y,item['label'],width=label_width-14)
            if view=='compare' and bar_right>bar_left:
                c.create_line(bar_left,y,bar_right,y,fill=COLORS['panel_soft'],width=7)
                end=bar_left+(item['value']-lo)/span*(bar_right-bar_left)
                c.create_line(zero,y,end,y,fill=col,width=7,tags=('segment','bar'))
                if negative:c.create_line(zero,y-7,zero,y+7,fill=COLORS['muted'])
            self._text(value_right,y,fmt(item['value']),anchor='e',bold=True,color=col,width=value_width-4)
            if percent_on:self._text(w-8,y,fmt_pct(item['value']/total*100),anchor='e',color=COLORS['muted'])
            self._hit_regions.append((start_x,y-rowh/2,w,y+rowh/2,item,total if share else None))

    def _item_at(self,event):
        for x0,y0,x1,y1,item,total in self._hit_regions:
            if x0<=event.x<=x1 and y0<=event.y<=y1:return item,total
        for cx,cy,outer,inner,start,extent,item,total in self._wedges:
            dx,dy=event.x-cx,cy-event.y;dist=math.hypot(dx,dy)
            angle=math.degrees(math.atan2(dy,dx))%360
            if inner<=dist<=outer and (start-angle)%360<=abs(extent):return item,total
        return None
    def _motion(self,event):
        hit=self._item_at(event);self.canvas.delete('tooltip')
        if hit:
            item,total=hit;text=item['label']+'\n'+self._formatter()(item['value'])
            if total:text+=' · '+fmt_pct(item['value']/total*100)
            if item['source'] is None:text+='\nSouhrn zbývajících položek; detail je v tabulce.'
            self._tooltip(text,event.x+12,event.y+15)
        self.canvas.configure(cursor='hand2' if hit and hit[0]['source'] is not None and self.on_item_click else 'arrow')
    def _click(self,event):
        hit=self._item_at(event)
        if hit and hit[0]['source'] is not None:self._notify(self.on_item_click,hit[0]['source'])
