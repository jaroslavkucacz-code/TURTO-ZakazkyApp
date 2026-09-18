# TURTO CRM – pilot 0.3.1 s místní ukázkou pro Windows

Tento balíček umožňuje vyzkoušet serverovou agendu Společnosti ve Windows bez instalace Pythonu. Jde o samostatný zkušební program. Běžné CRM spouštějte dál jeho stávající ikonou.

## Vyzkoušení hned, bez firemního serveru

1. Rozbalte stažený archiv a případný vnitřní ZIP do nové místní složky, například do Dokumentů. Ponechte pohromadě všechny soubory a složky, zejména `_internal` a `postgresql`.
2. Spusťte **TURTO-CRM-Mistni-Ukazka.exe** běžným dvojklikem. Nemusíte vyplňovat server, heslo, certifikát ani zapínat VPN. Příprava při spuštění může chvíli trvat.
3. Založte společnost tlačítkem **Nová společnost**, upravte poznámku a vyzkoušejte **Historii změn**.
4. Přepněte na **Pouze čtení**: společnosti lze prohlížet, tlačítka úprav jsou vypnutá. Na **Editor 1** nebo **Editor 2** lze přepnout zpět.
5. Pro souběžnou práci klikněte na **Otevřít druhé okno**. V obou oknech otevřete tutéž společnost. V prvním uložte změnu poznámky a ve druhém zkuste uložit jinou. Program oznámí, že záznam mezitím změnil jiný uživatel.

**Používejte jen vymyšlené údaje. Po zavření všech oken se ukázková databáze smaže; další spuštění začne znovu.** Nejde o místní kopii vašich skutečných dat. Otevření druhého okna uvnitř ukázky sdílí stejnou databázi; druhý dvojklik na EXE založí samostatnou novou ukázku.

Ukázka spouští přiložený PostgreSQL pouze na tomto PC, na adrese 127.0.0.1 a volném místním portu. Neinstaluje službu Windows, nepotřebuje oprávnění správce ani nemění firewall. Nepoužívá nastavení firemního připojení. Databázové procesy se ukončí i při násilném zavření programu; po takovém přerušení může zůstat dočasná složka v `%LOCALAPPDATA%\TURTO\CRM-Local-Demo`. Nové spuštění ji nepoužije. Distribuční licence PostgreSQL a jeho součástí jsou zachované v přiložené složce `postgresql`.

Tento pokus ověří Společnosti, oprávnění, historii a souběžné úpravy. Dostupnost firemního serveru, Wi-Fi a VPN se ověřuje zvlášť při následujícím zapojení.

## Pokud se ukázka nespustí

Verze 0.3.1 řeší chybu inicializace PostgreSQL při rozbalení programu do cesty s diakritikou, například `Prográmky`. Databázové soubory si pro takové spuštění zkopíruje do své dočasné místní složky; při běžném ukončení je odstraní spolu s ukázkovou databází. Kvůli této kopii může příprava trvat o chvíli déle. Není potřeba přejmenovat složku programu. Pokud diakritiku obsahuje i cesta profilu Windows, využije program její existující krátký název. Pokud takový název není dostupný, zobrazí konkrétní vysvětlení; nemění kvůli tomu nastavení Windows.

Od verze 0.3.1 zůstane při chybě otevřené okno s konkrétní příčinou a výpisem spuštění databáze. Klikněte na **Kopírovat podrobnosti** a vložte výsledek do zprávy. Protokol se také uloží do `%LOCALAPPDATA%\TURTO\CRM-Diagnostics`; přesná cesta je v okně. Protokol uvádí místní cesty, fázi spuštění a chybu pomocného programu. Nečte provozní CRM, nastavení firemního přihlášení ani systémový seznam hesel. Vygenerovaná hesla ukázky jsou z protokolu odstraněna. Příčina chyby místní ukázky sama o sobě nevypovídá o dostupnosti firemní VPN.

## Kontrola připojení z domova bez správce

1. Připojte běžnou firemní VPN a spusťte **TURTO-CRM-Kontrola-Pripojeni.exe**.
2. Pro dohodnutý server je předvyplněná adresa `192.168.8.240` a databázový port `5432`. Do pole Server nepatří cesta `\\192.168.8.240\turto`; samotná cesta ke složce není adresou databázové služby. Pokud správce určí jinou adresu/port, upravte je.
3. Klikněte na **Zkontrolovat** a potom **Kopírovat výsledek**. Stejný postup lze později zopakovat v kanceláři. Každá kontrola má vlastní protokol v `%LOCALAPPDATA%\TURTO\CRM-Diagnostics`.

Kontrola pouze otevře a zavře TCP spojení na zadaném databázovém portu a portu 445. Nemění firewall, VPN ani server a nepotřebuje databázové heslo. Dostupný port 445 potvrzuje jen dosažitelnost tohoto portu, nikoli oprávnění ke složce `turto`. Dostupný databázový port ještě neověřuje PostgreSQL, certifikát, přihlášení ani připravenost CRM. Nedostupný port nerozliší vypnutou službu, jiný port, firewall a omezení VPN. Přesnější rozlišení vyžaduje konfiguraci serveru a porovnání kancelář/domov.

## Zapojení do firemní sítě se správcem

1. Rozbalte celý ZIP do nové místní složky, například `C:\TURTO-pilot`. Ponechte u obou EXE i složku `_internal`. Program nespouštějte přímo z okna ZIP a nekopírujte pouze samotné EXE.
2. Správce připraví na firemním serveru PostgreSQL a zkušební databázi. Postup je ve složce `pro-spravce`, soubor `SERVER.md`. Balíček obsahuje umělá ukázková data, takže první pokus nevyžaduje převod vašich provozních dat.
3. Spusťte `TURTO-CRM-Sitovy-Pilot.exe`. V okně připojení vyplňte adresu serveru, port, testovací databázi, schéma, svůj osobní serverový účet a vyberte veřejný certifikát dodaný správcem.
4. Klikněte na **Uložit připojení**, zadejte heslo a stiskněte **Přihlásit**. Heslo se neukládá. Při dalším spuštění se načtou údaje připojení a znovu zadáte jen heslo.

V kanceláři používejte firemní Wi-Fi nebo kabelovou síť. Z domova nejprve připojte firemní VPN. Adresa serveru, databáze a přihlášení zůstávají stejné; samostatný domácí profil není potřeba. Při nedostupnosti sítě se zobrazí upozornění. Program neukládá obchodní data do místní náhradní kopie.

Pokud se při prvním startu objeví kontrola neznámého vydavatele, balíček nemá firemní podpis. Nechte správce posoudit schválení tohoto konkrétního balíčku podle interních pravidel. Neměňte kvůli němu plošné zabezpečení Windows.

## Co vyzkoušet na dvou počítačích

1. Přihlaste dva různé osobní účty s právem úprav do stejné testovací databáze a schématu. Založte firmu s názvem „TEST – síťový pilot“. Na druhém PC klikněte na **Vyhledat / obnovit**; firma se musí objevit.
2. Otevřete tuto firmu současně na obou PC. Na prvním změňte poznámku a uložte. Na druhém zkuste uložit vlastní změnu. Program musí oznámit, že záznam mezitím změnil jiný uživatel; první změna zůstane zachovaná.
3. Otevřete **Historii změn**. Musí ukázat autora a provedené úpravy. Pak přihlaste účet čtenáře: společnost lze otevřít, ale nelze založit novou ani uložit úpravu.
4. Z domova zapněte VPN a načtěte tutéž firmu. Bez VPN a mimo kancelář musí přihlášení selhat. Samotné připojení k běžné domácí Wi-Fi přístup nenahrazuje.
5. Pokud se spojení přeruší během ukládání a výsledek není jistý, po obnovení VPN použijte **Ověřit uložení**. Teprve podle výsledku pokračujte. Před zavřením takového okna pokud možno dokončete ověření.

Čtenář a druhý editor musí mít vlastní PostgreSQL účty; účet správce databáze není určený pro běžné testování. Ukázka obsahuje identity „Pilot – editor“ a „Pilot – čtenář“. Správce může pro druhého editora propojit další osobní serverový účet se zkušební identitou editora; historie navíc uchovává konkrétní serverový účet.

## Rozsah

Fungují Společnosti: vyhledání, založení, úprava základních údajů, aktivita, role odběratel/dodavatel a historie. Další agendy CRM zatím nejsou napojené. Změny testovací kopie se nepřenášejí do běžného CRM. Balíček nepoužívá jeho aktualizační kanál ani registraci instalace.

Pro firemní režim musí PostgreSQL běžet na firemním serveru nebo na vyhrazeném stroji v jeho síti. Pouhá sdílená složka pro tuto variantu nestačí. Místní ukázka nenahrazuje firemní databázi a síťový klient na ni při výpadku spojení automaticky nepřechází.
