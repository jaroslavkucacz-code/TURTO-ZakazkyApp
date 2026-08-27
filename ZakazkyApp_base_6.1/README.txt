ZAKÁZKY v0.7.0

HLAVNÍ ZMĚNY
- Jeden společný číselník Společnosti. Firma může být současně odběratel i dodavatel.
- Nová společnost má online našeptávání/vyhledávání v oficiálním ARES podle názvu nebo IČO.
- Tlačítko „Doplnit z ARES“ doplňuje u stávajících firem jednoznačné shody. Před spuštěním vytvoří zálohu.
- U společností se eviduje krátký název, oficiální název, IČO, DIČ, sídlo, právní forma, web.
- Poptávkové e-maily používají krátký název společnosti.
- Z nové poptávky lze rovnou založit chybějící Akci.
- E-mail se otevírá přes výchozí poštovní aplikaci Windows (mailto), takže není vázán na Outlook Classic.
- Opravený tmavý režim: písmo, vstupní pole, seznamy, checkboxy a pozadí používají jednotné barvy.
- Databáze se nově drží na stabilním místě mimo program:
  /home/oai/Documents/TURTO Zakazky/data/zakazky.db
  Na Windows se použije Dokumenty\TURTO Zakázky\data\zakazky.db.
- Při prvním spuštění se zkopíruje databáze z balíčku; budoucí aktualizace programu ji nepřepisují.
- Před migrací na v0.7 se automaticky vytvoří záloha.

ARES
Aplikace používá veřejné REST API ARES Ministerstva financí. Vyhledávání vyžaduje internetové připojení.
Pokud ARES není dostupný, společnost lze vždy zadat ručně.

OPRAVA 0.7.1
------------
Správa uživatelů nyní umožňuje:
- přidat uživatele
- upravit jméno
- aktivovat / deaktivovat uživatele
- smazat uživatele, pokud není použit v historii změn

Pokud je uživatel použit v historii Akcí nebo Poptávek, nelze ho kvůli zachování auditu úplně smazat; lze ho deaktivovat.

VERZE 0.8.0
-----------
• Každá Akce má nově časovou historii. V detailu Akce je vidět kdo, kdy a co provedl.
• Automaticky se zapisuje založení/úprava Akce, vytvoření Poptávky a označení odpovědi jako obdržené.
• Při migraci se vytvoří základ historie i ze starších Akcí a Poptávek. Pokud u starého záznamu nebyl uživatel uložen, je označen jako „Historický záznam“.
• TURTO je doplněno jako společnost a Jaroslav Kučera + Denisa Kovalová jsou navázáni jako interní osoby v Adresáři. E-maily zůstávají prázdné, dokud je nedoplníte.
• Našeptávače byly znovu sjednoceny na stabilní vlastní popup seznam.
• V Nastavení je „Kontrola databáze“, která ukáže počty záznamů a osiřelé vazby a zároveň vytvoří bezpečnostní kopii.
• Správa uživatelů z v0.7.1 zůstává zachována: přidat, upravit, aktivovat/deaktivovat a bezpečně smazat.
• Pracovní databáze zůstává mimo složku programu v Dokumenty\TURTO Zakázky\data\zakazky.db.

OPRAVA 0.8.1
------------
Opraven pád aplikace při spuštění. Funkce Detail / historie byla v předchozí verzi omylem vložena do nesprávné části programu.
Verze 0.8.1 byla po opravě skutečně spuštěna v testovacím grafickém prostředí a start aplikace proběhl úspěšně.

OPRAVA 0.8.2
------------
• Poptávku lze smazat samostatným tlačítkem „Smazat“, bez ohledu na vytvoření e-mailu.
• Před smazáním se zobrazí potvrzení.
• Informace o smazání se uloží do historie Akce včetně uživatele, společnosti a poptávané položky.
• Starší historie poptávky se při smazání nemaže.

VERZE 0.9.0
-----------
• Každá nová Poptávka má dvě samostatné společnosti:
  - „Poptáváno u“ = firma, které poptávku posíláte.
  - „Poptáváno pro“ = jedna konkrétní firma, pro kterou nabídku řešíte.
• Přehled Poptávek má samostatné sloupce Pro a U.
• Ve formuláři nové Poptávky je panel „Podobné předchozí poptávky“.
  Hledá podle stejné Akce a/nebo podobného poptávaného materiálu.
• Dvojklikem na starší podobnou poptávku zobrazíte její datum, Akci, Pro, U,
  materiál, příjemce, stav a poznámku.
• „Poptáváno pro“ se zapisuje také do nové historie Akce.
• Při založení Akce přímo z Poptávky se jako společnost předvyplní „Poptáváno pro“.
• Starší Poptávky se při migraci automaticky nepřiřazují k „Poptáváno pro“,
  protože by to bylo hádání. Zůstanou beze změny a údaj lze doplnit později.
• Databáze a dosavadní záznamy zůstávají zachované.

OPRAVA 0.9.1
------------
• Detail Společnosti nyní zobrazuje přímo všechny přiřazené osoby.
• Z detailu firmy lze osobu přidat, upravit nebo odebrat ze společnosti.
• Při založení/úpravě osoby je Společnost povinná a používá našeptávač.
• Poptávky jsou barevně rozlišeny: čekám = jemná žlutá, obdrženo = jemná zelená, čekání 7+ dní = oranžová.
• Vazba osoba ↔ společnost zůstává v databázi přes company_id.

OPRAVA 0.9.2
------------
• Příjemci e-mailu se nyní vždy načítají podle aktuální společnosti v poli „Poptáváno u“.
• Kontakty se obnoví i při ručním napsání přesného názvu společnosti, nejen po kliknutí v našeptávači.
• V seznamu příjemců se zobrazují pouze osoby přiřazené ke konkrétní společnosti.
• Osoby bez e-mailu jsou viditelně uvedené jako kontakt bez e-mailové adresy.
• Pokud firma nemá žádné osoby, lze z Poptávky rovnou přidat osobu k vybrané společnosti.

VERZE 0.9.3 – ARES
-------------------
• Hromadná aktualizace všech společností z ARES.
• Ukládá oficiální název, IČO, DIČ, sídlo, právní formu, datum vzniku,
  poslední změnu v ARES, CZ-NACE, finanční úřad, okres, obec a datum ověření.
• Navíc ukládá kompletní surový JSON z ARES pro budoucí využití dalších údajů.
• Firmy s IČO se aktualizují přímo podle IČO. Bez IČO se hledají podle názvu.
• Nejednoznačné shody se automaticky nepřepíší.
• Před hromadnou aktualizací se vytvoří záloha databáze.

VERZE 1.0.0
-----------
• Horní slogan byl odstraněn. Místo něj se zobrazuje dnešní datum velkým písmem.
• Pod datem je živý souhrn: počet hořících termínů a čekajících poptávek.
• Nastavení už není v levém menu; otevírá se ozubeným kolem vedle aktuálního uživatele.
• Vzhled aplikace se ukládá zvlášť pro každého uživatele.
• Správa uživatelů umožňuje přidat, upravit, deaktivovat a smazat uživatele.
  Smazání uživatele nijak nemění historické záznamy – historie zůstává přesně tak, jak byla.
• Stejný princip platí pro historické názvy firem a další historické údaje: auditní stopa se zpětně nepřepisuje.
• Dvojklik na Akci rovnou otevře její úpravu.
• Historie Akce je přímo pod editačními poli v jednom okně.
• Vazby Osoba ↔ Společnost zůstávají zachované a při migraci se znovu kontrolují.
• Ověřeno na testovací migraci: 141 společností, 339 akcí, 476 poptávek,
  19 osob, 47 materiálů, 2 uživatelé a 772 historických záznamů.
• Všech 19 osob zůstalo přiřazených ke společnosti.
• Aplikace byla po úpravách skutečně spuštěna v testovacím grafickém prostředí.

VERZE 1.1.0
-----------
• Nová záložka Úkoly / připomínky. Jedna Akce může mít libovolný počet úkolů
  s vlastním termínem, textem a poznámkou.
• Úkol zůstává aktivní, dokud jej ručně neoznačíte Hotovo. Dokončení i znovuotevření
  se zapisuje do historie Akce.
• Vedle uživatele je zvonek s odznakem počtu upozornění.
• Kliknutí na zvonek otevře přehled: po termínu, dnes a následující 3 dny.
  Zahrnuje úkoly, termíny Akcí a Poptávky čekající alespoň 3 dny.
• Jednou denně při prvním spuštění daného uživatele se přehled automaticky otevře,
  pokud obsahuje nějaké položky.
• V otevřené Akci je tlačítko Poptat. Otevře novou Poptávku s předvyplněnou Akcí
  a společností „Poptáváno pro“.
• V otevřené Akci lze rovnou přidat novou připomínku.
• Příjemci Poptávky se načítají podle interního company_id. Krátký ani oficiální
  název už není samotnou vazbou na kontakty.
• Historie a pracovní databáze zůstávají zachované.

VERZE 1.2.0
-----------
• Celá aplikace používá písmo Calibri.
• Horní tlačítko „+ Nová akce“ bylo odstraněno.
• Výběr uživatele je zobrazen jako profil s iniciálami a rozbalovacím menu.
• Hlavní tabulky podporují řazení kliknutím na hlavičku sloupce (▲ / ▼).
• Nová záložka Akce je za Úkoly a představuje skutečný projekt/stavbu.
• Původní Akce jsou Příležitosti/Akce a mohou být navázány na jednu společnou Akci.
• Adresář osob má Import Outlook/CSV a Export CSV.
• Import kontroluje duplicity podle e-mailu a páruje firmy na stabilní company_id.
• Při migraci se opravují jednoznačné vazby osob na společnosti.
• Poptávka může být bez vybraného kontaktu; adresáta lze doplnit až v Outlooku.

VERZE 1.3.0
-----------
• Záložka Akce se při migraci automaticky naplní ze stávajících Příležitostí/Akcí.
  Program slučuje pouze přesnou normalizovanou shodu názvu, aby omylem nespojil dvě různé stavby.
• Všechny stávající Příležitosti/Akce jsou na novou vrstvu Akcí navázané.
• Pole „Další krok“ bylo z detailu Příležitosti/Akce odstraněno; původní data v databázi
  se nemažou a zůstávají dostupná pro migraci/starší historii.
• „Co se řeší“ je našeptávač. Obsahuje dosavadní používané hodnoty a nové zadané
  položky se automaticky ukládají pro příště.
• Vráceno výraznější barevné podbarvení stavů a termínů.
• Vpravo v pracovních lištách jsou rychlé akce Editovat / Smazat a podle záložky
  také Poptat / Připomínka / Hotovo.
• Smazání vždy vyžaduje potvrzení. Příležitost/Akce s historií nebo Poptávkami se
  fyzicky nemaže, ale bezpečně archivuje jako Zrušeno.
• Kompletní historická data a vazby zůstávají zachované pro budoucí migrace.

OPRAVA 1.3.1 – AUTOMATICKÝ ARES
-------------------------------
• Při prvním spuštění této databáze se automaticky spustí kompletní aktualizace všech společností z ARES.
• Není potřeba ručně klikat na „Aktualizovat všechny z ARES“.
• Před automatickou aktualizací se vždy vytvoří bezpečnostní záloha databáze.
• Po úspěšném dokončení se do databáze uloží příznak, takže při dalších spuštěních se automatická aktualizace neopakuje.
• Ruční tlačítko pro ARES zůstává k dispozici pro pozdější aktualizaci podle potřeby.

OPRAVA 1.3.2
------------
• Poptávky načítají osoby výhradně přes stabilní company_id.
• Změna společnosti okamžitě překreslí checkboxy příjemců.
• Osoby bez e-mailu jsou viditelné, ale nelze je zvolit; bez kontaktu lze pokračovat do Outlooku.
• Barevné motivy jsou sjednocené pro panely, formuláře, pole, tabulky, hlavičky,
  checkboxy, comboboxy, Text/Listbox prvky a menu.
• Světlý režim používá jemně šedé pracovní pozadí; tmavý režim odstraňuje bílé plochy.
• Historie a stávající data se při opravě vazeb nemění.

OPRAVA STARTU 1.3.2
-------------------
• Opraven závěrečný spouštěcí blok aplikace, který se při předchozí úpravě motivů omylem odstranil.
• Aplikace byla po opravě skutečně spuštěna v testovacím grafickém prostředí a zůstala běžet.

VERZE 1.4.0
-----------
• ARES se už automaticky nespouští při startu aplikace.
• Testovací databáze v balíčku je předem migrovaná a vybrané jednoznačně ověřené
  společnosti mají ARES údaje předvyplněné už v balíčku.
• U Poptávek je nové pole „Řeší“; automaticky se předvyplní aktuální uživatel,
  lze jej změnit a v přehledu filtrovat podle uživatele.
• Stejné pole „Řeší“ je i u Úkolů, včetně filtru podle uživatele.
• Ranní upozornění na Úkoly respektuje aktuálního uživatele.
• Historické údaje o tom, kdo co vytvořil/upravil, zůstávají samostatné a nemění se
  při změně osoby „Řeší“.
• Správa uživatelů nadále používá samostatné aktuální účty; smazání účtu nemá
  zpětný vliv na textové historické záznamy.

OPRAVA 1.4.1 – STAVOVÁ BAREVNOST
--------------------------------
• Barevnost je nyní řízena stavem záznamu, ne jen motivem aplikace.
• Poptávky: modrá = čerstvá, žlutá = čeká 4–6 dní, oranžová = čeká 7+ dní,
  zelená = obdrženo.
• Úkoly: modrá = budoucí, žlutá = do 3 dnů, oranžová = dnes,
  červená = po termínu, zelená = hotovo.
• Příležitosti/Akce: aktivní = modrá, čekání = žlutá, blížící termín = oranžová,
  po termínu = červená, nabídka/připraveno = fialová, hotovo/vyhráno = zelená,
  zrušeno/prohráno = šedá.
• Barví se celý řádek v tabulce, ne jen text nebo jedna buňka.
• Stejný význam barev zůstává i v tmavém režimu; odstíny jsou jen ztlumené.
• Přidány stručné barevné legendy u Poptávek a Úkolů.

VERZE 1.5.0
-----------
• Záložka „Příležitosti/Akce“ byla přejmenována na „Příležitosti“.
• Poptávka si při výběru společnosti ukládá přímo interní company_id z našeptávače.
  Kontakty se načítají výhradně podle tohoto ID; krátký/oficiální název je jen zobrazení.
• U kontaktů je vidět počet nalezených osob a počet osob s e-mailem.
• Filtry datumů porovnávají celé datum, nikoli pouze den v měsíci.
• U Příležitostí jsou filtry přímo podle sloupců: Příležitost, Společnost,
  Co se řeší, Stav, Obchodník a Deadline.
• U Poptávek jsou filtry podle: Stav, Řeší, Pro, U koho poptáváme, Akce,
  Poptáváno a datum Poptáno.
• Datumové filtry podporují: Dříve než, Později než, Do data, Od data a Přesně.
• Přidána tlačítka „Zrušit filtry“.
• Smazání uživatele nezasahuje do textových historických záznamů.
• Datová migrace zachovává stávající záznamy a vazby.

VERZE 1.6.0
-----------
• Opravena vazba Poptávka → Společnost → Osoby přes stabilní company_id.
• Ověřen konkrétní scénář MAVI → Marek Forejt → marek.forejt@mavi.cz bez duplicit.
• Smazání Poptávky je nyní archivace: z běžného seznamu zmizí, ale data a historie zůstávají.
• Lze volitelně zobrazit archivované Poptávky.
• Správa uživatelů má jasné tlačítko „Smazat“.
• Smazání uživatele neovlivní historické záznamy; nelze smazat právě aktivního ani posledního aktivního uživatele.

VERZE 1.8.0
-----------
• Pole „Poptávám u“ je znovu našeptávač, nikoli dlouhý rozbalovací seznam.
• Našeptávač si po výběru ukládá konkrétní company_id; kontakty se načítají podle něj.
• Poptávky mají oddělené akce „Archivovat“ a „Smazat“.
• Archivovat = záznam zůstane v databázi a lze jej později zobrazit.
• Smazat = záznam se fyzicky odstraní z tabulky requests po potvrzení.
• Historické události zůstávají zachované; vazba related_request_id se před smazáním odpojí.
• Před smazáním se do historie zapíše samostatný otisk s údaji o Poptávce.

VERZE 1.9.0
-----------
• Duplicitní název Akce odstraněn; obchodní agenda se jmenuje Příležitosti.
• Navigace: Přehled → Příležitosti → Poptávky → Adresář osob → Společnosti → Akce → Úkoly.
• Všechna známá datumová pole se při kliknutí na sloupec řadí podle celého data.
• Doplněno datumové řazení Přijato, Obdrženo, Zahájení a Dokončení.
• V Poptávce je výrazný panel Komu zaslat s checkboxy osob podle company_id.
• Doplněno pole Jiný e-mail.
• Při editaci Poptávky se dříve vybraní příjemci znovu předvyberou.
• Uložení Poptávky samo neotevírá e-mail.

VERZE 2.0.0
-----------
• Opraveno tlačítko Editovat u Poptávek.
• Editace otevírá existující Poptávku přes rid a ukládá změny UPDATE do stejného záznamu.
• Editují se společnosti, Akce, data, materiál, poznámka, příjemci i uživatel Řeší.
• Dvojklik na Poptávku otevírá editaci.
• Editace se zapisuje do historie Akce.
• Přidána možnost Obnovit archivovanou Poptávku.
• U všech osob se kontroluje platnost company_id vůči tabulce Společnosti.
• ARES identita společnosti (zejména IČO) slouží jako stabilní identita firemního záznamu;
  pokud ji obsahuje i starší záznam osoby, použije se pro jednoznačné přiřazení.
• U starších textových vazeb se osoba přiřadí jen při jediné přesné shodě názvu společnosti.
• E-mail, telefon ani jiné kontaktní údaje osoby se migrací nepřepisují.

VERZE 2.3.0
-----------
• Nový modro-bílý vizuální styl podle schváleného návrhu.
• Přehled má nové KPI karty; čísla nemají samostatnou masku/pozadí.
• Přidány Rychlé akce, Moje nejbližší úkoly a Čekající poptávky.
• Opraven zámek SQLite při ukládání/editaci/dokončení Úkolu.
• U Poptávky příjemce není povinný pro uložení; lze jej doplnit později.
• Kontakty se obnovují i po Enter/opuštění našeptávače a lze přidat osobu přímo z Poptávky.
• Opraveny krátké transakce při ukládání/editaci Poptávek.
• Společnosti lze archivovat/obnovit; fyzicky smazat lze společnost bez navázaných dat.
• Přidán výběrový export jednotlivých oblastí dat do ZIP/JSON.
• Kompletní export/import databáze zůstává zachován.

VERZE 2.4.0
-----------
• Opraven celý tok Poptávky: znovu fungují company_id/requested_for_id/action_id.
• Po výběru společnosti se osoby načítají podle company_id a zobrazují se jako checkboxy.
• Tlačítko „+ Přidat osobu“ otevře osobu s předvybranou společností a po uložení kontakty obnoví.
• Poptávku lze uložit i bez příjemce.
• Opraveno ukládání Poptávky bez SQLite zámku.
• Čekající Poptávky se znovu zobrazují na Přehledu; NULL archived se bere jako aktivní záznam.
• U Akcí přidáno „Sloučit s jinou Akcí“. Poptávky ani jejich historické řádky se nepřepisují.
• U Společností dvojklik otevírá editaci.
• „Kontrola databáze“ přejmenována na „Zkontrolovat data“ a nyní vždy ukáže výsledek integrity a vazeb.
• Ve Správě uživatelů je jasné tlačítko „Smazat uživatele“.
• Kompletní i výběrový export vždy otevře dialog „Uložit jako“ pro výběr cíle.
• V Nastavení jsou viditelná tlačítka kompletního exportu/importu i výběrového exportu.

VERZE 2.5.0
-----------
• Dvojklik na Osobu otevírá editaci.
• Všechny dvojkliky nad tabulkami reagují pouze na datový řádek; záhlaví nic neotevírá.
• Větší dialogová okna lze měnit velikost a maximalizovat.
• Opraven panel Čekající poptávky v Přehledu; používá robustní podmínku i pro starší archived hodnoty.
• Přidána Windows DPI awareness, aby se celé UI nenechávalo bitmapově škálovat a text byl ostřejší.
• Sjednoceny základní fonty na Calibri v celých velikostech a zvýšen kontrast drobných textů.
• Vytvoření e-mailu na Windows nejprve zkusí klasický Outlook 365 přes COM a teprve potom mailto/defaultní Outlook.

VERZE 2.6.0
-----------
• Přidána vestavěná offline Nápověda podle procesů programu.
• Pod verzí programu je uvedeno „Vytvořil Ing. Jaroslav Kučera“.
• Outlook: pokud se nelze připojit ke klasickému Outlooku, program již automaticky nespouští nový Outlook přes mailto.

VERZE 2.7.0
-----------
• Opravena Nápověda: nové řádky a odstavce se zobrazují správně, bez viditelného \n.
• Enter potvrzuje/ukládá dialog; Esc zavírá bez uložení. V multiline poznámkách Enter zůstává nový řádek.
• V Adresáři osob přidán import kontaktů z CSV a vCard (.vcf).
• Import probíhá přes jednotlivé dialogy, kde lze doplnit chybějící údaje a přiřadit společnost.
• Při duplicitním e-mailu lze otevřít existující osobu k doplnění nebo kontakt přeskočit.
• Přidán export osob do CSV a vCard.
• U Příležitostí lze měnit stav přímo ze seznamu bez otevření editace.
• Rychlá změna stavu se zapisuje do historie.

VERZE 2.8.0
-----------
DŮLEŽITÉ: Tato verze jako jediná provede při prvním spuštění jednorázovou obnovu
pracovní databáze podle původního souboru 00_AKCE(1).xlsx. Předchozí testovací
databázi před resetem automaticky zazálohuje. Marker v backup/v280_original_excel_reset_done.txt
zajistí, že se reset v2.8 neopakuje.

Další verze programu již tento reset používat nebudou a budou pokračovat s aktuálními
pracovními daty vytvořenými po prvním spuštění v2.8.

• Původní Excel je přiložen ve složce original_source pro kontrolu původu dat.
• Outlook: program se připojí ke spuštěnému klasickému Outlooku, nebo jej přes COM spustí,
  pokud je zavřený. Nový Outlook/přihlašovací průvodce se automaticky nespouští.
• Nastavení obsahuje „Vytvořit zástupce na ploše“ s ikonou TURTO.
• Spustit_Zakazky.bat používá pyw/pythonw, takže běžné spuštění nevytváří druhé
  konzolové okno na hlavním panelu.

VERZE 2.9.0
-----------
• Od této verze se již NIKDY automaticky neresetuje pracovní databáze podle původního Excelu.
• Data vytvořená při běžném používání se zachovávají do dalších verzí.
• Jednorázově se obnoví Adresář Osob ze zálohy, kterou v2.8 vytvořila před resetem.
  Obnovují se pouze osoby a jejich vazby na společnosti; testovací Příležitosti,
  Poptávky, Úkoly ani jiné testovací obchodní záznamy se nevracejí.
• U historických Poptávek importovaných z původního Excelu zůstává „Řeší“ prázdné,
  pokud původní data odpovědnou osobu neobsahovala.

VERZE 2.10.0
------------
• „Řeší“ u Poptávek se nedoplňuje z technického updated_by.
• „Import původního Excelu“ a „Historický záznam“ jsou z pole Řeší odstraněny.
• Skutečně přiřazení uživatelé zůstávají zachováni.
• Logo TURTO je nastaveno jako ikona hlavního okna a identita aplikace pro Windows taskbar.
• Reset databáze z v2.8 je definitivně odstraněn.

VERZE 2.11.0
------------
• Správa uživatelů má vždy viditelná tlačítka Přidat, Upravit, Smazat, Aktivní/neaktivní a Zavřít.
• Pole „Název příležitosti/akce“ je sjednoceno na „Název příležitosti“; Akce zůstává nadřazený projekt.
• „Čekám na dodavatele“ již není hlavní stav Příležitosti. Staré záznamy se převedou na Rozpracováno.
• Čekající Poptávky jsou v detailu Příležitosti zobrazeny samostatně jako „Čekám na poptávku / odpověď“.
• U hlavních datumových polí a filtrů je měsíční rozbalovací kalendář; databázový formát zůstává YYYY-MM-DD.
• „Další krok“ je v přehledech nahrazen skutečnou „Poznámkou“.
• Přesné duplicity Společností se při migraci bezpečně sloučí se zachováním vazeb.
• „Poptáváno u“ i firemní filtry zobrazují každou společnost pouze jednou.
• Dialogová okna se centrují nad rodičovským oknem, tedy na stejném monitoru jako hlavní program.
• Windows AppUserModelID je stabilní „TURTO.Zakazky“, aby připnutý zástupce a běžící aplikace sdílely TURTO ikonu.
• Výchozí databáze pro novou instalaci je aktualizována na schéma 2.11; existující pracovní databáze se samozřejmě nepřepisuje.

VERZE 2.12.0
------------
• V dialogu Příležitosti je už jen jedno názvové pole „Akce“. Interní vazby a historie zůstávají zachované.
• Přímo z Příležitosti lze tlačítkem „+ Nová společnost“ založit Společnost do stejné databáze a ihned ji použít.
• Měsíční kalendáře jsou v češtině; dnešní datum je zvýrazněné žlutě a zvolené datum modře.
• Všechna existující filtrovací pole jsou přesunuta do řádku přímo nad odpovídající sloupce tabulek.
• Společnosti a Adresář osob jsou v levém menu nad Nápovědou; Nápověda je dole nad verzí programu.
• U Osob je „Funkce“ samostatný doplňovatelný číselník (Stavbyvedoucí, Jednatel, Obchodní zástupce atd.).
• Existující Funkce se při migraci automaticky převedou do číselníku.
• Duplicitní Osoby se bezpečně deduplikují primárně podle e-mailu.
• Při zakládání Osoby program upozorní na shodu e-mailu nebo jména ve stejné Společnosti.
• Osobu lze označit jako neaktivní, znovu aktivovat nebo trvale smazat; lze zobrazit i neaktivní Osoby.
• V Poptávkách je „Pro“ přejmenováno na „Odběratel“ a „U“ na „Dodavatel“ v tabulce, filtrech i dialogu.
• Databázový formát dat zůstává YYYY-MM-DD.

VERZE 2.13.0
------------
• Nabídka Akcí v dialogu Úkolu je deduplikovaná podle normalizovaného názvu.
• Stejná deduplikace je použita i v dialogu Poptávky.
• Filtrovací buňky jsou dynamicky svázané se skutečnými šířkami sloupců Treeview.
  Při ručním zúžení/rozšíření sloupce, změně velikosti okna i horizontálním posunu
  zůstává filtr zarovnaný nad příslušným sloupcem.
• Dialog Poptávky má pole Akce a tlačítko „+ Nová akce“ ve společném zarovnaném řádku.
• V Nastavení je nová sekce „Číselníky“.
• Správa číselníků zahrnuje Funkce osob, Poptávané zboží / materiály,
  Co se řeší a Obchodníky.
• U položek číselníku lze Přidat, Upravit, Aktivovat/deaktivovat a Smazat.
• Pokud je položka už použitá, při smazání se pouze deaktivuje, aby zůstala
  zachovaná historie.

VERZE 2.14.0
------------
• Správce číselníků lze otevřít přímo z dialogových oken tlačítkem „⚙ Spravovat“.
• Osoba → Funkce osob.
• Příležitost → Obchodníci a Co se řeší.
• Poptávka → Poptávané zboží / materiály.
• Po zavření správce se nabídka v otevřeném dialogu okamžitě znovu načte.
• U Akce je nové pole GPS souřadnice, např. 49.1951, 16.6068.
• GPS se validuje na rozsah zeměpisné šířky a délky.
• Tlačítko „Otevřít v mapě“ otevře místo v Google Maps bez potřeby API klíče.
• Pokud GPS není vyplněné, lze mapu otevřít podle adresy Akce.
• Schéma databáze rozšířeno o projects.gps_coordinates.

VERZE 2.15.0
------------
• Příležitosti jsou při každém obnovení výchozím způsobem řazeny podle Přijato:
  nejnovější nahoře, starší níže, záznamy bez data nakonec.
• Poptávky jsou obdobně řazeny podle Poptáno: nejnovější nahoře, bez data nakonec.
• Po novém uložení nebo úpravě se seznamy znovu načtou v tomto výchozím pořadí.
• Přidána samostatná sekce MIVO v levém menu.
• MIVO zobrazuje pouze Poptávky, jejichž DODAVATEL je MIVO.
• Běžná sekce Poptávky naopak Poptávky s Dodavatelem MIVO nezobrazuje.
• Při změně Dodavatele na MIVO / z MIVO se záznam po uložení automaticky zobrazí
  ve správné sekci; nic se nekopíruje a používá se jedna databáze.
• Sekce MIVO má stejnou práci s Poptávkami: nová, editace, archivace, mazání,
  Obdrženo dnes, e-mail a filtry.
• Nová Poptávka založená ze sekce MIVO má Dodavatele MIVO předvyplněného.
• Odběratel u Poptávky je volitelný.
• Akce u Poptávky je volitelná.
• U Dodavatele i Odběratele lze přímo z dialogu založit „+ Nová společnost“.
  Nová firma se zapíše do společné databáze a okamžitě se nabídne v obou polích.

VERZE 2.16.0
------------
• Opraveno načítání historických Poptávek MIVO:
  rozpoznává se oficiální název, krátký název MIVO i stará vazba supplier_id.
• Staré záznamy, kde byl Dodavatel MIVO jen v původní tabulce suppliers,
  se při migraci znovu správně navážou na společnost MIVO.
• Filtry s číselníkovými hodnotami lze ovládat psaním i myší.
  Kliknutí do prázdného filtru zobrazí nabídku; psaní ji průběžně zužuje.
• Stejné chování je u Příležitostí, Poptávek, MIVO a filtru Řeší u Úkolů.
• Příležitosti už nefiltrují Co se řeší ani Poznámku.
• Příležitosti mají filtry Stav, Přijato, Deadline, Příležitost, Společnost a Obchodník.
• Poptávky už nefiltrují Odběratele ani Poptáváno; zůstává Stav, Řeší,
  Poptáno, Dodavatel a Akce.
• MIVO používá obdobně zjednodušené filtry.
• Kalendář má nový kompaktní vzhled, české měsíce a dny, odlišené víkendy,
  zvýrazněný dnešek, vybraný den, tlačítko Dnes a Vymazat datum.
• Čekající Poptávky se už barevně nerozlišují podle stáří celého řádku.
  Dlouhé čekání (7+ dní) se označí pouze symbolem ⚠ ve sloupci Poptáno.
• U Příležitostí je odstraněno horní pole pro změnu stavu.
  Kliknutím do buňky Stav se otevře rozbalovací seznam přímo v tabulce
  a změna se ihned uloží do databáze a historie.
• Detail Příležitosti zobrazuje stejnou Akci u dalších společností
  včetně společnosti, data Přijato a stavu.
• Dvojklik na související Příležitost ji otevře v novém samostatném okně.

VERZE 2.17.0
------------
• U čekajících Poptávek 7+ dní se již nezobrazuje symbol ⚠. Červeně se podbarví pouze pole s datem ve sloupci Poptáno.

VERZE 2.18.0
------------
• Deadline Příležitosti už nebarví celý řádek; prošlý termín se zvýrazní pouze červeně v buňce Deadline.
• Stav „Čekám na obchodníka / odběratele“ odstraněn; staré záznamy se převedou na Rozpracováno.
• Odstraněny prázdné nadpisy nad sloupci, které nemají filtr.
• Zrušit filtry přesunuto doprava do filtrovacího řádku.
• + Nová příležitost / + Nová poptávka přesunuty na řádek názvu sekce úplně vpravo.
• Opravena vazba Akce při uložení Poptávky: existující název se dohledá i bez interního ID našeptávače.
• Správa uživatelů má ovládací tlačítka ukotvená dole a seznam se zmenšuje nad nimi.
• Přidán stav Poptávky „Bez odezvy“. Nevyplňuje Obdrženo, nepočítá se mezi čekající a nezvýrazňuje stáří Poptáno.
• „Bez odezvy“ funguje i v MIVO.

VERZE 2.19.0
------------
• Zrušit filtry je kompaktní a umístěné úplně vpravo.
• Změna stavu Příležitosti zachová aktivní řazení a vybraný řádek zůstane dohledatelný.
• Bez odezvy je zeleně stejně jako Obdrženo.
• Koncept e-mailu se vytvoří i bez příjemce v poli Komu; trvalá kopie zůstává.
• Outlook nejprve otevře běžný nový e-mail, takže se použije výchozí editor, formátování a podpis; text programu se vloží nad podpis.
• Poptávky dodavatele MIVO se nezobrazují v Přehledu čekajících poptávek.

VERZE 2.20.0
------------
• Jednorázový import osob vytěžených z dodaného exportu e-mailové komunikace.
• Kontakty se deduplikují podle e-mailové adresy; existující údaje se nepřepisují, doplňují se jen prázdná pole.
• Společnosti jsou párovány primárně podle firemní e-mailové domény a na oficiální názvy v databázi; chybějící společnosti se založí.
• Zjevné obecné/automatické adresy a kontakty bez spolehlivého přiřazení společnosti jsou vynechány.
• Import se spustí pouze jednou; další verze už data osob nemažou ani znovu nepřepisují.

VERZE 2.21.0
------------
• Druhý jednorázový import osob z exportu mail2.CSV.
• Kontakty již existující podle e-mailu se neduplikují.
• Společnost se přebírá z již ověřeného firemního doménového přiřazení v databázi, případně pouze z právního názvu nalezeného v podpisu. Nejasné kontakty se automaticky nezakládají.
• Import se při aktualizaci existující instalace spustí pouze jednou a další data nemaže.

VERZE 2.22.0
------------
• Proveden technický audit vazeb Společnosti → Osoby → Akce/Příležitosti → Poptávky → Úkoly → Historie.
• Přidáno 18 databázových indexů pro rychlejší načítání vazeb, stavů a termínů.
• Část globálních refresh_all nahrazena cíleným obnovením pouze dotčených částí programu.
• Čekající Poptávky pro MIVO, Bez odezvy a archivované záznamy nevstupují do Přehledu.
• Dialogová okna mají posuvný obsah a počáteční velikost se drží v pracovní ploše monitoru hlavního programu.
• „Zrušit filtry“ je kompaktní, úplně vpravo a zobrazí se pouze při aktivním filtru.
• Dynamické filtrování respektuje skutečná čísla sloupců i sloupce bez filtru.
• Funkce osob byly normalizovány do 18 praktických kategorií; chybně vytěžené věty byly odstraněny.
• Z obou mailových exportů byly konzervativně doplněny prázdné hodnoty Přijato u spolehlivě identifikovaných Příležitostí.
• U několika Akcí byla doplněna lokalita (např. Kladno, Beroun, Benešov, České Budějovice, Plzeň), pouze pokud byla jednoznačně obsažena v názvu.

VERZE 2.23.0
------------
• Kliknutí kamkoli mimo rozbalovací nabídku filtru ji automaticky zavře.
• Kliknutí do samotného seznamu ji nezavře před výběrem položky.

VERZE 2.24.0
------------
• V MIVO byl odstraněn zbytečný sloupec Dodavatel.
• Dialog MIVO už nezobrazuje „Podobné předchozí poptávky“.
• Předmět e-mailu je v MIVO plně volně editovatelný a automatika jej následně nepřepisuje.
• Dialogová okna se znovu otevírají ve větší praktické výchozí velikosti, ale stále zůstávají uvnitř monitoru a mají posuvníky.
• Při vložení textu do nového Outlook e-mailu se za „Předem velice děkuji,“ nepřidává prázdný řádek navíc.
• + Nový úkol, + Nová Akce, + Nová osoba a + Nová společnost jsou na řádku názvu záložky úplně vpravo, stejně jako u Příležitostí a Poptávek.
• Sloučení s jinou Akcí používá našeptávací vyhledávání psaním i výběr myší.

VERZE 2.25.0 – UZAVŘENÍ ŘADY 2
------------------------------
• Dialogová okna mají větší výchozí šířku a stále se drží v pracovní ploše monitoru.
• Víceřádková textová pole zalamují text po slovech.
• Barvy stavů jsou mírně výraznější při zachování tlumeného vzhledu.
• Nápověda byla aktualizována podle aktuálního chování programu.
• Tato verze uzavírá vývojovou řadu 2.

VERZE 3.0.0
-----------
• Zahájena vývojová řada 3 nad stabilním základem v2.25 FINAL.
• Opraven našeptávač: po výběru položky myší nebo Enterem se nabídka okamžitě zavře a znovu se sama neotevře.
• Výška dialogových oken se nově řídí skutečnou výškou obsahu. Kratší dialogy už nemají velkou prázdnou plochu.
• Komfortní větší šířka dialogů a posuvníky zůstávají zachovány.

VERZE 3.1.0
-----------
• České řazení textu v tabulkách i databázových seznamech včetně Č, Ř, Š, Ž, diakritiky a českého CH.
• Historie Příležitostí zobrazuje UTC časy převedené na Europe/Prague, automaticky včetně letního/zimního času.
• Dialogy lze posouvat kolečkem přes celý formulář i nad vnořenými poli.
• Canvas dialogů používá barvu motivu, takže při větším okně nezůstává dole bílá plocha.
• Našeptávače podporují šipky nahoru/dolů a potvrzení Enterem.
• Po výběru položky se rozbalovací seznam zavře.

VERZE 3.2.0
-----------
• Přidán speciální uživatel TEST.
• Přepnutí na TEST vytvoří konzistentní dočasnou kopii aktuální ostré databáze.
• Veškeré databázové změny TEST uživatele probíhají pouze v této kopii.
• Při přepnutí z TEST na normálního uživatele nebo při zavření aplikace se testovací databáze zahodí.
• Pokud aplikace v TEST režimu spadne, zbylá testovací relace se automaticky odstraní při příštím spuštění.
• V horní liště je v TEST režimu výrazné upozornění „TESTOVACÍ REŽIM – ZMĚNY SE NEUKLÁDAJÍ“.

VERZE 3.3.0
-----------
• Kolečko myši nad rozbalovacím Comboboxem již nikdy nemění jeho vybranou hodnotu.
• V dialogových oknech stejné kolečko místo toho posouvá celý formulář.
• Oprava je globální pro pole „Řeší“ i ostatní rozbalovací seznamy v aplikaci.

VERZE 3.4.0
-----------
• Rozbalovací nabídky našeptávačů jsou ukotvené ke svému vstupnímu poli.
• Při scrollování dialogu se otevřená nabídka přepočítá podle skutečné pozice pole v Canvasu.
• Ukotvení funguje také při tažení posuvníku a změně velikosti nebo polohy dialogu.
• Pokud se zdrojové pole odscrolluje mimo viditelnou část, nabídka se automaticky zavře.

VERZE 4.0.0
-----------
• Nové hlavní uživatelské rozhraní inspirované odsouhlaseným návrhem v4.
• Hlavní navigace je horizontálně nahoře; pracovní plocha má více místa pro tabulky a formuláře.
• Nový tmavý vizuální styl s decentní zlatou akcentní barvou; světlý režim zůstává dostupný.
• Aktivní sekce, hlavní akční tlačítka a TEST režim jsou vizuálně výraznější.
• TEST režim má velký žlutý banner nahoře a informační stav ve spodním řádku.
• Přidán spodní stavový řádek s verzí/databází a autorským údajem.
• Tabulky mají v tmavém režimu tlumené stavové barvy místo světlých pastelových ploch.
• Zachovány všechny funkce řady 3.x včetně českého řazení, testovací databáze,
  klávesového ovládání našeptávačů, scrollování dialogů a ukotvení popupů.

VERZE 4.1.0
-----------
• Pole Řeší v Poptávkách a Úkolech používá nový ukotvený výběr přímo uvnitř dialogu.
• Seznam osob už není samostatné plovoucí okno (Toplevel), takže při scrollování nemůže odjet mimo formulář.
• Výběr podporuje kliknutí, psaní, šipky nahoru/dolů, Enter a Escape.
• Po volbě se seznam zavře; při kliknutí jinam se také zavře.
• Nový tmavý/zlatý vizuál řady 4 se při prvním spuštění v4.1 aktivuje i pro uživatele, kteří měli ze starší verze uložený světlý motiv.

VERZE 5.1.0 FUNCTIONAL
----------------------
• Výchozí pracovní aplikace znovu obsahuje plnou funkcionalitu poslední stabilní v4.1.
• Zachovány jsou Příležitosti, Akce, Poptávky, MIVO, Úkoly, Společnosti, Osoby,
  historie, Outlook koncepty, ARES, GPS/mapy, číselníky, import/export, zálohy,
  uživatelé, TEST režim, filtry, české řazení a našeptávání.
• Produkční verzi spouštějte přes Spustit_Zakazky_v5.bat.
• Rozpracovaný Qt vzhled je přibalen odděleně jako qt_preview_v5.py a není výchozí,
  dokud nedosáhne stejné funkční parity.

VERZE 5.2.0 – VIZUÁLNÍ REVIZE
-----------------------------
• Zachována plná funkcionalita pracovní v5.1 / v4.1; změny této verze jsou primárně vizuální.
• Nový propracovanější tmavý/zlatý CRM vzhled: jemnější paleta, vyšší tabulkové řádky,
  modernější vstupní pole, klidnější tlačítka a výraznější aktivní navigace.
• Horní lišta nově používá značku TURTO | Zakázky CRM a méně technický vzhled.
• Záhlaví jednotlivých stránek mají podtituly vysvětlující obsah sekce.
• Dashboard má sjednocenou typografii a klidnější vizuální hierarchii.
• Produkční aplikaci lze spustit přes Spustit_Zakazky_v5.vbs bez černého konzolového okna.
• Spustit_Zakazky_v5.bat používá pyw, pokud je dostupné; Spustit_DIAGNOSTIKA.bat zůstává pro řešení chyb.

VERZE 5.3.0 – DIALOGY A DETAILY
-------------------------------
• Zachována funkční logika v5.2; tato verze pokračuje ve vizuálním sjednocování.
• Všechny posuvné dialogy mají novou vlastní hlavičku s názvem a kontextovým podtitulem.
• Formuláře mají větší vnitřní odsazení, čistší pozadí a sjednocené nativní Text/Listbox prvky.
• Horizontální posuvník dialogu se zobrazuje jen tehdy, když je opravdu potřeba.
• Filtry mají jednotné decentní popisky a hlavní toolbar tlačítka používají společný styl.
• TEST režim a tmavý/zlatý motiv byly vizuálně doladěny.
• Produkční tiché spuštění bez černé konzole zůstává přes Spustit_Zakazky_v5.vbs.

VERZE 5.4.0 – ČITELNOST A TERMÍNY
---------------------------------
• Stavové barvy v tmavém režimu jsou světlejší a čitelnější; text zůstává převážně světlý.
• Rozpracováno, Čekám, Hotovo/Obdrženo, Nabídka, po termínu a archiv mají výraznější, ale stále tlumené odstíny.
• Odstraněny plovoucí Label widgety používané pro zvýraznění Deadline a starých Poptávek.
• Upozornění na hořící datum je nyní součástí hodnoty buňky (⚠ datum), takže se při vertikálním ani horizontálním scrollu nemůže odtrhnout od řádku.
• Zachována plná funkcionalita a vizuální úpravy v5.3.

VERZE 5.5.0 – KLIDNĚJŠÍ CRM
----------------------------
• Plošné stavové barvy jsou výrazně ztlumené; tabulky jsou klidnější a čitelnější.
• Hořící datum zůstává označené přímo v buňce symbolem ⚠, blížící se termín symbolem ●.
• Zvýraznění termínů není plovoucí widget, takže se při scrollování neodtrhne.
• Hover záhlaví tabulek používá zlaté pozadí a tmavý kontrastní text.
• Ruční řazení se po odchodu ze záložky zahodí; při návratu se obnoví výchozí pořadí.
  Příležitosti a Poptávky se vracejí k nejnovějším datům nahoře, záznamy bez data na konec.
• Akce se nově standardně řadí podle data zahájení, nejnovější nahoře.
• Dashboard má nový CRM FOCUS pruh: jednou větou ukáže příležitosti po termínu,
  blížící se deadliny, staré poptávky bez odezvy a úkoly k řešení.

VERZE 5.6.0 – NABÍDKY / PDF
---------------------------
• Přidána nová hlavní záložka Nabídky.
• PDF nabídku lze importovat a přiřadit k dodavateli, odběrateli a Akci/Příležitosti.
• Ukládá se původní PDF cesta, SHA-256 otisk, surový text a rozpoznané položky.
• Původní celý název položky zůstává uložen v original_name.
• Pro cenovou historii se vytváří samostatný item_key; původní názvy se ukládají jako aliasy.
• Detail nabídky zobrazuje položky, množství, MJ, jednotkovou cenu a celkovou cenu.
• Duplicitní import stejného PDF je blokován podle SHA-256.
• PDF parser je první obecná verze. Pro přesnou funkční paritu s TURTO Nabídky V4.7.24
  bude potřeba převzít její skutečné parsery/importní pravidla z posledního ZIPu této aplikace.
• Pro PDF import je potřeba pdfplumber; lze nainstalovat přes Nainstalovat_knihovny.bat.

VERZE 5.7.0 – TURTO NABÍDKY + AKTUALIZACE
-----------------------------------------
• Do CRM je přímo zabalen skutečný parser z TURTO Nabídky V4.7.24.
• Podporuje rozpoznání cenových nabídek Leviat a GEROtop, včetně GEROtop obrázků,
  technických popisů, původních cen, slev a cen po slevě.
• Import PDF předvyplní rozpoznaného dodavatele, číslo nabídky, datum a zkusí
  přiřadit reference k existující Akci/Příležitosti.
• Zachovává se plný original_name a samostatný canonical item_key pro historii cen.
• Novější kratší základní název dokáže sjednotit starší názvy s dovětkem; aliasy zůstávají.
• Obrázky mají evidovaný zdroj nabídky a novější nabídka nepřepíše obrázek starším.
• Přidána infrastruktura automatických aktualizací:
  Nastavení → Aktualizace aplikace → zdroj může být OneDrive/síťová složka nebo HTTPS.
  Aplikace čte latest.json, ověří SHA-256, stáhne ZIP, po ukončení se aktualizuje a znovu spustí.
  Databáze v Dokumenty\TURTO Zakazky se nepřepisuje.
• Automatická kontrola běží několik sekund po startu, pokud je zdroj aktualizací nastaven.
• Pro první nastavení aktualizačního kanálu je nutné jednou určit trvalý zdroj
  (např. synchronizovanou OneDrive složku, firemní síťovou složku nebo GitHub/HTTPS).

VERZE 5.7.1 – TEST AKTUALIZAČNÍHO KANÁLU
----------------------------------------
• Testovací servisní vydání pro ověření automatické aktualizace z v5.7.
• Databázové schéma zůstává 5.7; uživatelská data se nemění.
• Po úspěšné aktualizaci musí hlavní okno zobrazit verzi 5.7.1.

VERZE 5.7.2 – GITHUB AKTUALIZAČNÍ KANÁL
---------------------------------------
• Výchozí aktualizační kanál je veřejný GitHub repozitář TURTO-ZakazkyApp.
• Starý OneDrive aktualizační adresář se automaticky nahradí GitHub zdrojem.
• Databáze a firemní data zůstávají pouze lokálně.
