from __future__ import annotations

import re
from pathlib import Path

SETUP_TTK = '''    def _setup_ttk(self):
        s=ttk.Style(self); s.theme_use('clam')
        s.configure('Dark.Treeview',background=COLORS['panel'],fieldbackground=COLORS['panel'],foreground=COLORS['text'],rowheight=28,borderwidth=0,font=('Calibri',10))
        s.configure('Dark.Treeview.Heading',background=COLORS['panel_soft'],foreground=COLORS['text'],font=('Calibri',10,'bold'),relief='flat',padding=(7,6))
        s.map('Dark.Treeview',background=[('selected',COLORS['panel_soft'])],foreground=[('selected',COLORS['text'])])

        # Readonly TCombobox uses its own state map on Windows. Without an explicit
        # map the OS theme can force a pale field while leaving the text white.
        s.configure('Dark.TCombobox',
                    fieldbackground=COLORS['panel_soft'],background=COLORS['panel_soft'],
                    foreground=COLORS['text'],arrowcolor=COLORS['text'],
                    bordercolor=COLORS['border'],lightcolor=COLORS['border'],
                    darkcolor=COLORS['border'],borderwidth=1,relief='flat',
                    padding=(9,6),font=('Calibri',11))
        s.map('Dark.TCombobox',
              fieldbackground=[('readonly',COLORS['panel_soft']),('focus',COLORS['panel_alt'])],
              background=[('readonly',COLORS['panel_soft']),('active',COLORS['panel_alt'])],
              foreground=[('readonly',COLORS['text']),('disabled',COLORS['muted'])],
              selectbackground=[('readonly',COLORS['panel_soft'])],
              selectforeground=[('readonly',COLORS['text'])],
              bordercolor=[('focus',COLORS['teal']),('readonly',COLORS['border'])],
              arrowcolor=[('readonly',COLORS['text']),('active',COLORS['teal'])])
        self.option_add('*TCombobox*Listbox.background', COLORS['panel_soft'])
        self.option_add('*TCombobox*Listbox.foreground', COLORS['text'])
        self.option_add('*TCombobox*Listbox.selectBackground', COLORS['teal'])
        self.option_add('*TCombobox*Listbox.selectForeground', '#06251D')
        self.option_add('*TCombobox*Listbox.font', 'Calibri 11')
'''

TOP_BLOCK = '''        right=tk.Frame(self,bg=COLORS['bg']); right.pack(side='left',fill='both',expand=True)
        top=tk.Frame(right,bg=COLORS['bg'],height=92); top.pack(fill='x'); top.pack_propagate(False)
        left=tk.Frame(top,bg=COLORS['bg']); left.pack(side='left',fill='y',padx=22,pady=(10,8))

        period_box=tk.Frame(left,bg=COLORS['bg'])
        period_box.pack(side='left',fill='y',padx=(0,12))
        tk.Label(period_box,text='OBDOBÍ',bg=COLORS['bg'],fg='#B7C4D3',font=('Calibri',8,'bold')).pack(anchor='w',pady=(0,4))
        self.period_var=tk.StringVar(value=self.cfg.get('default_period','2026-08'))
        self.period_cb=ttk.Combobox(period_box,textvariable=self.period_var,width=12,state='readonly',style='Dark.TCombobox')
        self.period_cb.pack(anchor='w')
        self.period_cb.bind('<<ComboboxSelected>>',lambda e:self.refresh_current())

        mode_box=tk.Frame(left,bg=COLORS['bg'])
        mode_box.pack(side='left',fill='y',padx=(0,12))
        tk.Label(mode_box,text='ROZSAH',bg=COLORS['bg'],fg='#B7C4D3',font=('Calibri',8,'bold')).pack(anchor='w',pady=(0,4))
        self.mode_var=tk.StringVar(value='Měsíc')
        mode=ttk.Combobox(mode_box,textvariable=self.mode_var,values=['Měsíc','YTD','Rok','Posledních 12 měsíců'],width=20,state='readonly',style='Dark.TCombobox')
        mode.pack(anchor='w'); mode.bind('<<ComboboxSelected>>',lambda e:self.refresh_current())

        compare=tk.Frame(left,bg=COLORS['panel'],highlightbackground=COLORS['border'],highlightthickness=1,bd=0,padx=12,pady=7)
        compare.pack(side='left',anchor='s',pady=(18,0))
        tk.Label(compare,text='POROVNÁNÍ',bg=COLORS['panel'],fg=COLORS['muted'],font=('Calibri',7,'bold')).pack(anchor='w')
        tk.Label(compare,text='Předchozí rok',bg=COLORS['panel'],fg=COLORS['text'],font=('Calibri',10,'bold')).pack(anchor='w',pady=(1,0))

        actions=tk.Frame(top,bg=COLORS['bg']); actions.pack(side='right',padx=22,pady=24)
'''


def apply_patch(root: str | Path) -> None:
    root = Path(root)
    constants = root / 'src' / 'constants.py'
    ui = root / 'src' / 'ui.py'

    if constants.exists():
        s = constants.read_text(encoding='utf-8')
        s = re.sub(r"APP_VERSION\s*=\s*'[^']+'", "APP_VERSION = '0.1.6'", s, count=1)
        constants.write_text(s, encoding='utf-8')

    if ui.exists():
        s = ui.read_text(encoding='utf-8')

        # Replace the entire ttk setup method up to _build_layout.
        a = s.find('    def _setup_ttk(self):')
        b = s.find('\n    def _build_layout(self):', a)
        if a >= 0 and b > a:
            s = s[:a] + SETUP_TTK + s[b:]

        # Replace only the top-filter portion of _build_layout; keep sidebar/actions code.
        start = s.find("        right=tk.Frame(self,bg=COLORS['bg']); right.pack(side='left',fill='both',expand=True)")
        end = s.find("        tk.Button(actions,text='Importovat data'", start)
        if start >= 0 and end > start:
            s = s[:start] + TOP_BLOCK + s[end:]

        ui.write_text(s, encoding='utf-8')

    (root / 'ZMENY_0.1.6.txt').write_text(
        'TURTO – Měsíční přehledy v0.1.6\n'
        '- Výrazně lepší čitelnost horní lišty a filtrů.\n'
        '- Tmavé comboboxy i ve Windows readonly režimu.\n'
        '- Vyšší kontrast, větší písmo a větší aktivní plocha filtrů.\n'
        '- Samostatné popisky OBDOBÍ / ROZSAH.\n'
        '- Porovnání s předchozím rokem v samostatné kartě.\n'
        '- Tmavý a kontrastní rozevírací seznam.\n',
        encoding='utf-8')
