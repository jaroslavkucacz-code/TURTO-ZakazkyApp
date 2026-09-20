"""Compact native map background menu; no records are changed by this control."""
import tkinter as tk
from tkinter import ttk


class BasemapMenu(ttk.Menubutton):
    def __init__(self, parent, variable, command):
        super().__init__(parent, text='Podklad mapy', compound='image',
                         direction='below', takefocus=True, cursor='hand2')
        self._turto_view_only = True
        self.variable = variable
        self.menu = tk.Menu(self, tearoff=False)
        for label, value in (('Mapa', 'map'), ('Ortofoto ČR', 'orthophoto')):
            self.menu.add_radiobutton(label=label, value=value, variable=variable, command=command)
        self.configure(menu=self.menu)
        self._icon_color = None
        self._tip = None
        self._tip_after = None
        self._draw_icon()
        self.bind('<<ThemeChanged>>', self._draw_icon, add='+')
        self.bind('<Enter>', self._schedule_tip, add='+')
        self.bind('<FocusIn>', self._schedule_tip, add='+')
        for event in ('<Leave>', '<FocusOut>', '<ButtonPress-1>', '<Destroy>'):
            self.bind(event, self._hide_tip, add='+')

    def _draw_icon(self, event=None):
        # Draw at triple resolution so the layer symbol stays crisp in both themes.
        from PIL import Image, ImageDraw, ImageTk
        color = ttk.Style(self).lookup('TMenubutton', 'foreground') or '#263f4a'
        if color == self._icon_color:
            return
        rgb = tuple(c // 256 for c in self.winfo_rgb(color))
        size = max(22, round(22 * float(self.tk.call('tk', 'scaling')) / (96 / 72)))
        scale = size * 3 / 24
        image = Image.new('RGBA', (size * 3, size * 3))
        draw = ImageDraw.Draw(image)
        for points in (((3,8),(12,3),(21,8),(12,13),(3,8)),
                       ((3,12),(12,17),(21,12)), ((3,16),(12,21),(21,16))):
            draw.line([(round(x*scale), round(y*scale)) for x,y in points],
                      fill=(*rgb,255), width=max(2,round(1.6*scale)), joint='curve')
        self._icon = ImageTk.PhotoImage(image.resize((size,size),Image.Resampling.LANCZOS),master=self)
        self._icon_color = color
        self.configure(image=self._icon)

    def _schedule_tip(self, event=None):
        self._hide_tip()
        self._tip_after = self.after(450, self._show_tip)

    def _show_tip(self):
        self._tip_after = None
        if not self.winfo_viewable() or self.menu.winfo_ismapped():
            return
        self._tip = tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        label = 'Ortofoto ČR' if self.variable.get() == 'orthophoto' else 'Mapa'
        ttk.Label(tip,text='Podklad mapy: '+label,padding=(9,5),relief='solid').pack()
        tip.update_idletasks()
        x = max(0,self.winfo_rootx()+self.winfo_width()-tip.winfo_reqwidth())
        y = max(0,self.winfo_rooty()-tip.winfo_reqheight()-4)
        tip.geometry(f'+{x}+{y}')
        tip.lift()

    def _hide_tip(self, event=None):
        if self._tip_after:
            self.after_cancel(self._tip_after)
            self._tip_after = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
