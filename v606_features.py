# TURTO CRM 6.0.13 incremental features
# Process-oriented branched help kept current with actual CRM behavior.
import datetime

def apply(M):
    # Legacy warning wrappers stay in place; the final stability layer applies current thresholds.
    old_mivo=M.App.refresh_mivo_requests
    def mivo(self):
        return old_mivo(self)
    M.App.refresh_mivo_requests=mivo

    old_req=M.App.refresh_requests
    def requests(self):
        return old_req(self)
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
'Přehled':('Přehled','''Přehled ukazuje otevřené položky, termíny, čekající poptávky, nejbližší úkoly a barevné rychlé akce. Slouží jako denní startovní obrazovka. Hořící termíny jsou zvýrazněné u data, aby barva celého řádku zůstala přehledná.'''),
'Akce':('Akce','''Akce je nadřazený projekt/stavba, pod kterou mohou být různé Příležitosti od více společností. Založte ji před Příležitostí, pokud chcete související obchodní případy držet pohromadě. Akce lze upravovat a slučovat; historie vazeb se má zachovat.'''),
'Příležitosti':('Příležitosti','''Příležitost představuje konkrétní obchodní případ. Vyberte Akci, společnost, obchodníka, stav, deadline, Co se řeší a Poznámku. Stav lze měnit i rychle ze seznamu. Audit sleduje stav i další důležité změny. Barvy: Rozpracováno modře, Připraveno/Nabídka tyrkysově, Hotovo zeleně, problém/po termínu červeně.'''),
'Poptávky':('Poptávky','''Poptávku lze založit z Příležitosti nebo samostatně. Vyberte společnost a příjemce, upravte text a následně vytvořte koncept e-mailu. Nejčastěji a naposledy používané kontakty pro konkrétní společnost se řadí nahoru, ale nic se samo nezaškrtává. Pokud je stav Čekám déle než 3 dny, u data Poptáno se zobrazí jediný symbol ⚠. Po obdržení odpovědi se stáří původního data jako problém nezvýrazňuje.'''),
'MIVO':('MIVO','''MIVO je samostatná evidence poptávek směřovaných na MIVO. Délka čekání nemění barvu celého řádku. Pokud je stav Čekám déle než 10 dní, u data Poptáno se zobrazí pouze jeden symbol ⚠. Po stavu Obdrženo se stáří Poptáno jako problém nezvýrazňuje.'''),
'Nabídky':('Nabídky','''Modul Nabídky slouží pro zpracování a evidenci PDF nabídek. Uchovává původní názvy položek, historii cen, aliasy a zdroj obrázků. Nabídku lze postupně provázat s Akcí/Příležitostí; tento modul dále rozšiřujeme směrem k databázi cen a budoucímu generování vlastních nabídek.'''),
'Úkoly':('Úkoly','''Úkol se váže k Příležitosti, má termín, text a přiřazeného uživatele. Přehled zobrazuje nejbližší úkoly. Vytváření a úpravy Úkolů se zapisují do auditu. Termíny po splatnosti jsou vizuálně zvýrazněné.'''),
'Společnosti':('Společnosti','''Společnosti jsou společný adresář odběratelů i dodavatelů. Ukládají oficiální název, IČ a další údaje; lze využít ARES. Osoby jsou na společnost navázané. Mazání nebo deaktivace nesmí zničit historické záznamy.'''),
'Osoby':('Osoby','''Osoba je kontakt přiřazený ke společnosti a používá se zejména u příjemců Poptávek. Kontakty lze spravovat v adresáři. Častěji používané kontakty se nabízejí výše, ale nejsou automaticky zaškrtávány.'''),
'Uživatelé':('Uživatelé','''Běžný uživatel může pouze zvolit svoji identitu. Správa uživatelů je dostupná pouze ADMINovi. Poslední běžný uživatel se ukládá lokálně podle PC, takže společná síťová databáze nepřepíná uživatele ostatním počítačům.'''),
'ADMIN':('ADMIN','''ADMIN je systémový účet chráněný heslem. Slouží pro správu uživatelů, síťové databáze, aktualizací a auditní HISTORIE. ADMIN se nesmí automaticky přihlásit bez zadání hesla.'''),
'Síťová databáze':('Síťová databáze','''V ADMIN části lze vytvořit síťovou databázi z aktuálních dat nebo připojit existující DB dostupnou přes LAN/VPN. Před migrací se vytváří záloha. Pokud síťová databáze není dostupná, klient se nesmí automaticky přepnout na starou lokální kopii. Tím se zabrání paralelním rozdílným datům.'''),
'HISTORIE':('HISTORIE','''ADMIN HISTORIE eviduje auditované změny: čas, uživatele, PC, objekt, pole a původní/novou hodnotu. U podporovaných změn se ve sloupci Stav zobrazí LZE VRÁTIT. Označte řádek a klikněte na ↶ Vrátit změnu. Před provedením se zobrazí potvrzení. Vrácený záznam se označí VRÁCENO a samotný ADMIN zásah se znovu zapíše do historie. Operace, které nelze bezpečně obnovit, zůstávají pouze pro čtení.'''),
'Aktualizace':('Aktualizace','''CRM kontroluje aktualizace při startu i během běhu přibližně každých 10 minut. Nabídka verze obsahuje stručné release notes. Firemní automatickou kontrolu řídí ADMIN. Nápověda se aktualizuje s každým vydáním.'''),
'Ovládání':('Ovládání','''Našeptávače jsou určené i pro práci z klávesnice. Pište část názvu, šipkami ↑/↓ můžete změnit zvýrazněnou položku a Enter ji ihned potvrdí a zavře nabídku. Pokud nic ručně nevyberete, Enter vezme první nabízenou položku. Další Enter pak může potvrdit celý dialog. Esc dialog zavírá; v multiline Poznámce Enter vytváří nový řádek.'''),
'Řazení a filtry':('Řazení a filtry','''Kliknutím na záhlaví lze tabulku dočasně seřadit. Při přechodu na jinou záložku se ruční řazení zruší a při návratu se použije výchozí pořadí agendy. Filtry slouží jen pro aktuální pracovní pohled a nemění data.'''),
'Okna a monitory':('Okna a monitory','''Hlavní CRM se spouští maximalizované. Dialogy se otevírají velké, ale mají zůstat uvnitř dostupné plochy monitoru a lze je okamžitě zmenšit. Všechna dialogová okna patří pod hlavní aplikaci.'''),
'Zálohy a přenos':('Zálohy a přenos','''Před zásadními databázovými operacemi vytvářejte zálohu. Cílový stav počítá s instalačním balíčkem pro nový PC a jednoduchou obnovou/připojením ke společné firemní databázi. Programové soubory a firemní data jsou oddělené.''')}
            title=ttk.Label(content,text='',style='Section.TLabel');title.pack(anchor='w');txt=tk.Text(content,wrap='word',font=('Calibri',11),padx=12,pady=12);txt.pack(fill='both',expand=True,pady=(6,0))
            def show(key):
                h,b=topics[key];title.configure(text=h);txt.configure(state='normal');txt.delete('1.0','end');txt.insert('1.0',b);txt.configure(state='disabled')
            for key in topics:ttk.Button(nav,text=key,command=lambda k=key:show(k)).pack(fill='x',pady=1)
            show('Začínáme')
        except:pass
    M.App.build_help=help_page
