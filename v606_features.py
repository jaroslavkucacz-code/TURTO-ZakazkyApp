# TURTO CRM 6.0.6 incremental features
# Help kept current, MIVO date-only warning, stronger status contrast, taller dialogs/maximized main window.
import datetime

def apply(M):
    # Stronger status colors. MIVO row status remains semantic; waiting age is handled in Poptáno only.
    old_theme=M.App.apply_theme
    def theme(self,*a,**k):
        r=old_theme(self,*a,**k)
        dark='tmav' in (self.theme.get() if hasattr(self,'theme') else '').lower()
        pal={
          'status_active':(('#b9daf2','#0d3554') if not dark else ('#315f7f','#f4fbff')),
          'status_offer':(('#a8e2da','#064f48') if not dark else ('#19786f','#f0fffd')),
          'status_done':(('#b8e2c2','#145326') if not dark else ('#397349','#f0fff3')),
          'status_wait':(('#ffe49a','#5c4300') if not dark else ('#80651b','#fff5c7')),
          'status_soon':(('#ffc184','#713400') if not dark else ('#92501d','#fff0df')),
          'status_late':(('#f6abab','#7d1111') if not dark else ('#8e3737','#fff0f0')),
          'status_cancel':(('#d8dde2','#3f4850') if not dark else ('#525d66','#f5f7f8')),
          'status_won':(('#a9dab7','#124b23') if not dark else ('#2d7444','#effff4'))}
        def walk(w):
            try:
                if w.winfo_class()=='Treeview':
                    for tag,(bg,fg) in pal.items():w.tag_configure(tag,background=bg,foreground=fg)
                for c in w.winfo_children():walk(c)
            except:pass
        self.after_idle(lambda:walk(self));return r
    M.App.apply_theme=theme

    # MIVO: do not color whole row by waiting age. Only mark Poptáno after >10 days while still waiting.
    old_mivo=M.App.refresh_mivo_requests
    def mivo(self):
        r=old_mivo(self)
        try:
            today=datetime.date.today()
            for iid in self.mivo_tree.get_children():
                vals=list(self.mivo_tree.item(iid,'values'))
                state=str(vals[0] if vals else '')
                # Restore row color by status only.
                self.mivo_tree.item(iid,tags=('status_done',) if state.casefold().startswith('obdrž') else ('status_active',))
                # Poptáno is column 2 in current MIVO table. Prefix ! only when still waiting >10 days.
                if len(vals)>2 and state.casefold().startswith('ček'):
                    raw=str(vals[2]).replace('⚠','').replace('!','').strip()
                    parsed=None
                    for fmt in ('%d.%m.%Y','%Y-%m-%d'):
                        try:parsed=datetime.datetime.strptime(raw,fmt).date();break
                        except:pass
                    if parsed and (today-parsed).days>10:vals[2]='!  '+raw
                    else:vals[2]=raw
                    self.mivo_tree.item(iid,values=vals)
        except:pass
        return r
    M.App.refresh_mivo_requests=mivo

    # Dialogs: taller by default but always within screen. Main window starts maximized.
    def dialog_size(win,w=980,h=760):
        try:
            win.update_idletasks();sw=win.winfo_screenwidth();sh=win.winfo_screenheight();ww=min(max(520,int(w)),max(520,sw-60));hh=min(max(420,int(h)),max(420,sh-90));win.geometry(f'{ww}x{hh}+{max(0,(sw-ww)//2)}+{max(0,(sh-hh)//2)}');win.resizable(True,True)
        except:pass
    M.enable_dialog_maximize=dialog_size

    # Replace Help page content after original builder runs. Keep it maintained with every release.
    old_help=M.App.build_help
    def help_page(self):
        old_help(self)
        try:
            p=self.tabs['help']
            for c in p.winfo_children():c.destroy()
            import tkinter as tk
            from tkinter import ttk
            ttk.Label(p,text='Nápověda TURTO Zakázky CRM',style='PageTitle.TLabel').pack(anchor='w')
            ttk.Label(p,text=f'Aktuální pro verzi {M.APP_VERSION}',style='PageSubtitle.TLabel').pack(anchor='w',pady=(0,12))
            txt=tk.Text(p,wrap='word',font=('Calibri',11),padx=14,pady=12)
            txt.pack(fill='both',expand=True)
            body='''ZÁKLADNÍ PRINCIP\nCRM eviduje Příležitosti, Akce, Poptávky, MIVO, Nabídky, Úkoly, Společnosti a Osoby. Běžný uživatel si v horní liště pouze volí svoji identitu. Poslední běžný uživatel se pamatuje samostatně pro konkrétní PC.\n\nADMIN\nÚčet ADMIN je chráněný heslem. Pouze ADMIN spravuje uživatele, síťovou databázi, firemní aktualizace a auditní HISTORII. ADMIN se po spuštění automaticky nepřihlašuje bez hesla.\n\nDATABÁZE A FIREMNÍ PROVOZ\nCRM může pracovat lokálně nebo se společnou síťovou databází dostupnou přes LAN/VPN. Při nedostupné síťové DB se klient z bezpečnostních důvodů nepřepne na starou lokální kopii. V ADMIN části lze síťovou DB otestovat.\n\nHISTORIE\nADMIN HISTORIE eviduje auditované změny včetně uživatele a počítače. Pokrytí auditu a bezpečné vracení změn se postupně rozšiřuje; historie se nemaže při změně uživatele.\n\nAKTUALIZACE\nCRM kontroluje nové verze při startu i během běhu. Nabídka aktualizace obsahuje stručný přehled změn. Firemní automatickou kontrolu může řídit ADMIN.\n\nŘAZENÍ TABULEK\nKliknutím na záhlaví lze tabulku dočasně seřadit. Po přechodu na jinou záložku se ruční řazení zahodí a při návratu se použije výchozí pořadí dané agendy.\n\nBARVY A TERMÍNY\nBarvy stavů jsou významové a mají samostatnou paletu pro světlý a tmavý režim. Rozpracováno je modré, Připraveno/Nabídka tyrkysová, Hotovo zelené, čekání žluté, blížící se problém oranžový a po termínu červený. Hořící termíny používají výrazné !.\n\nMIVO\nU MIVO délka čekání nemění barvu celého řádku. Pokud je stav Čekám a od data Poptáno uplynulo více než 10 dní, zvýrazní se samotný termín symbolem !. Jakmile je nabídka obdržena, stáří původní poptávky se jako problém neoznačuje.\n\nPOPTÁVKY A PŘÍJEMCI\nPoptávky jsou navázané na společnost a osoby. CRM má připravenou evidenci četnosti používání příjemců; cílem je řadit nejčastěji používané kontakty výše bez jejich automatického zaškrtávání.\n\nPOZNÁMKY\nVíceřádková textová pole včetně Poznámky používají Calibri.\n\nBEZPEČNOST DAT\nPřed zásadní migrací databáze se vytváří záloha. Síťový režim používá čekání na zapisovací zámek, aby krátký souběh více uživatelů nezpůsoboval okamžitou chybu.\n\nNápověda se od této verze aktualizuje společně s každou další verzí CRM.'''
            txt.insert('1.0',body);txt.configure(state='disabled')
        except:pass
    M.App.build_help=help_page

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after(150,lambda:self.state('zoomed'))
        except:pass
        return r
    M.App.__init__=init
