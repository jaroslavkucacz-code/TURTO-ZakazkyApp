# TURTO CRM 6.0.7 incremental features
# Process-oriented branched help + corrected request/MIVO warning rules.
import datetime

def apply(M):
    # MIVO: only original warning triangle, only waiting >10 days; row color by state only.
    old_mivo=M.App.refresh_mivo_requests
    def mivo(self):
        r=old_mivo(self)
        try:
            today=datetime.date.today()
            for iid in self.mivo_tree.get_children():
                vals=list(self.mivo_tree.item(iid,'values'));state=str(vals[0] if vals else '')
                self.mivo_tree.item(iid,tags=('status_done',) if state.casefold().startswith('obdrž') else ('status_active',))
                if len(vals)>2:
                    raw=str(vals[2]).replace('⚠','').replace('!','').strip();parsed=None
                    for fmt in ('%d.%m.%Y','%Y-%m-%d'):
                        try:parsed=datetime.datetime.strptime(raw,fmt).date();break
                        except:pass
                    vals[2]=('⚠  '+raw) if state.casefold().startswith('ček') and parsed and (today-parsed).days>10 else raw
                    self.mivo_tree.item(iid,values=vals)
        except:pass
        return r
    M.App.refresh_mivo_requests=mivo

    # Classic requests: less aggressive than old 3-day rule. Keep row state semantics; warning belongs to waiting date.
    old_req=M.App.refresh_requests
    def requests(self):
        r=old_req(self)
        try:
            today=datetime.date.today()
            for iid in self.request_tree.get_children():
                vals=list(self.request_tree.item(iid,'values'))
                # Locate first displayed date-like cell and normalize old warning symbols.
                for j,v in enumerate(vals):
                    raw=str(v).replace('⚠','').replace('!','').strip();parsed=None
                    for fmt in ('%d.%m.%Y','%Y-%m-%d'):
                        try:parsed=datetime.datetime.strptime(raw,fmt).date();break
                        except:pass
                    if parsed:
                        age=(today-parsed).days
                        if age>=11:vals[j]='⚠  '+raw
                        elif age>=6:vals[j]='•  '+raw
                        else:vals[j]=raw
                        break
                self.request_tree.item(iid,values=vals)
        except:pass
        return r
    M.App.refresh_requests=requests

    # Branched, process-oriented help: left navigation + detailed process page.
    old_help=M.App.build_help
    def help_page(self):
        old_help(self)
        try:
            p=self.tabs['help']
            for c in p.winfo_children():c.destroy()
            import tkinter as tk
            from tkinter import ttk
            ttk.Label(p,text='Nápověda TURTO Zakázky CRM',style='PageTitle.TLabel').pack(anchor='w')
            ttk.Label(p,text=f'Procesní nápověda • verze {M.APP_VERSION}',style='PageSubtitle.TLabel').pack(anchor='w',pady=(0,10))
            body=ttk.Frame(p);body.pack(fill='both',expand=True);nav=ttk.Frame(body,width=250);nav.pack(side='left',fill='y',padx=(0,10));content=ttk.Frame(body);content.pack(side='left',fill='both',expand=True)
            topics={
'Začínáme':('Začínáme','''CRM je společné pracovní místo pro obchodní a zakázkovou agendu. Typický tok je: založit Akci → vytvořit Příležitost → podle potřeby vytvořit Poptávku/MIVO → evidovat nabídku a úkoly → průběžně měnit stav. V horní liště vždy zkontrolujte aktivního uživatele; na každém PC se pamatuje poslední běžný uživatel.'''),
'Přehled':('Přehled','''Přehled ukazuje otevřené položky, termíny, čekající poptávky, nejbližší úkoly a rychlé akce. Slouží jako denní startovní obrazovka. Hořící termíny jsou zvýrazněné u data, aby barva celého řádku zůstala přehledná.'''),
'Akce':('Akce','''Akce je nadřazený projekt/stavba, pod kterou mohou být různé Příležitosti od více společností. Založte ji před Příležitostí, pokud chcete související obchodní případy držet pohromadě. Akce lze upravovat a slučovat; historie vazeb se má zachovat.'''),
'Příležitosti':('Příležitosti','''Příležitost představuje konkrétní obchodní případ. Vyberte Akci, společnost, obchodníka, stav, deadline, Co se řeší a Poznámku. Stav lze měnit i rychle ze seznamu. Změny stavu se zapisují do ADMIN HISTORIE. Barvy: Rozpracováno modře, Připraveno/Nabídka tyrkysově, Hotovo zeleně, problém/po termínu červeně.'''),
'Poptávky':('Poptávky','''Poptávku lze založit z Příležitosti nebo samostatně. Vyberte společnost a příjemce, upravte text a následně vytvořte koncept e-mailu. U čekajících klasických poptávek je 0–5 dní bez varování, 6–10 dní mírné upozornění a 11+ dní výrazné upozornění u data. Po obdržení odpovědi stáří původního data nemá být problém. CRM připravuje řazení příjemců podle četnosti použití.'''),
'MIVO':('MIVO','''MIVO je samostatná evidence poptávek směřovaných na MIVO. Délka čekání nemění barvu celého řádku. Pokud je stav Čekám déle než 10 dní, u data Poptáno se zobrazí pouze symbol ⚠. Po stavu Obdrženo se stáří Poptáno jako problém nezvýrazňuje.'''),
'Nabídky':('Nabídky','''Modul Nabídky slouží pro zpracování a evidenci PDF nabídek. Uchovává původní názvy položek, historii cen, aliasy a zdroj obrázků. Nabídku lze postupně provázat s Akcí/Příležitostí; tento modul dále rozšiřujeme směrem k databázi cen a budoucímu generování vlastních nabídek.'''),
'Úkoly':('Úkoly','''Úkol se váže k Příležitosti, má termín, text a přiřazeného uživatele. Přehled zobrazuje nejbližší úkoly. Dokončení a znovuotevření se eviduje v historii případu. Termíny po splatnosti jsou vizuálně zvýrazněné.'''),
'Společnosti':('Společnosti','''Společnosti jsou společný adresář odběratelů i dodavatelů. Ukládají oficiální název, IČ a další údaje; lze využít ARES. Osoby jsou na společnost navázané. Mazání nebo deaktivace nesmí zničit historické záznamy.'''),
'Osoby':('Osoby','''Osoba je kontakt přiřazený ke společnosti a používá se zejména u příjemců Poptávek. Kontakty lze spravovat v adresáři. Častěji používané kontakty budou postupně nabízené výše, ale nebudou automaticky zaškrtávány.'''),
'Uživatelé':('Uživatelé','''Běžný uživatel může pouze zvolit svoji identitu. Správa uživatelů je dostupná pouze ADMINovi. Poslední běžný uživatel se ukládá lokálně podle PC, takže společná síťová databáze nepřepíná uživatele ostatním počítačům.'''),
'ADMIN':('ADMIN','''ADMIN je systémový účet chráněný heslem. Slouží pro správu uživatelů, síťové databáze, aktualizací a auditní HISTORIE. ADMIN se nesmí automaticky přihlásit bez zadání hesla.'''),
'Síťová databáze':('Síťová databáze','''V ADMIN části lze vytvořit síťovou databázi z aktuálních dat nebo připojit existující DB dostupnou přes LAN/VPN. Před migrací se vytváří záloha. Pokud síťová databáze není dostupná, klient se nesmí automaticky přepnout na starou lokální kopii. Tím se zabrání paralelním rozdílným datům.'''),
'HISTORIE':('HISTORIE','''ADMIN HISTORIE eviduje auditované změny: čas, uživatele, PC, objekt, pole a původní/novou hodnotu. Audit postupně rozšiřujeme na všechny důležité operace. U podporovaných změn bude ADMIN moci provést bezpečné vrácení; vrácení samo vytvoří další auditní záznam.'''),
'Aktualizace':('Aktualizace','''CRM kontroluje aktualizace při startu i během běhu přibližně každých 10 minut. Nabídka verze obsahuje stručné release notes. Firemní automatickou kontrolu řídí ADMIN. Nápověda se od verze 6.0.6 aktualizuje s každým vydáním.'''),
'Řazení a filtry':('Řazení a filtry','''Kliknutím na záhlaví lze tabulku dočasně seřadit. Při přechodu na jinou záložku se ruční řazení zruší a při návratu se použije výchozí pořadí agendy. Filtry slouží jen pro aktuální pracovní pohled a nemění data.'''),
'Zálohy a přenos':('Zálohy a přenos','''Před zásadními databázovými operacemi vytvářejte zálohu. Cílový stav počítá s instalačním balíčkem pro nový PC a jednoduchou obnovou/připojením ke společné firemní databázi. Programové soubory a firemní data jsou oddělené.''')}
            title=ttk.Label(content,text='',style='Section.TLabel');title.pack(anchor='w');txt=tk.Text(content,wrap='word',font=('Calibri',11),padx=12,pady=12);txt.pack(fill='both',expand=True,pady=(6,0))
            def show(key):
                h,b=topics[key];title.configure(text=h);txt.configure(state='normal');txt.delete('1.0','end');txt.insert('1.0',b);txt.configure(state='disabled')
            for key in topics:ttk.Button(nav,text=key,command=lambda k=key:show(k)).pack(fill='x',pady=1)
            show('Začínáme')
        except:pass
    M.App.build_help=help_page
