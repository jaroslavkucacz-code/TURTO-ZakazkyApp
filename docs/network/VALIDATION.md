# Stav přechodu na PostgreSQL

## Diagnostika a cesty s diakritikou 0.3.1

Při zkoušce z cesty `Prográmky/TURTO CRM – zkouška` byl v [běhu 35381388876](https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/actions/runs/35381388876) reprodukován pád nativního `initdb` s chybou `invalid byte sequence for encoding UTF8` během dokončení inicializace. Ukázka proto při neASCII cestě distribuce připraví vlastní kopii přiloženého PostgreSQL ve své dočasné složce. Soukromá data ukázky se nemísí se serverovými daty.

Windows test nyní spouští skutečné EXE z přesunuté cesty s diakritikou, ověřuje souběh úprav, oprávnění a běžné i násilné ukončení. Další scénář odebere `postgres.bki` pouze v testovací kopii balíčku, vyvolá reálnou chybu `initdb` a ověří zachování protokolu po úklidu i tlačítko jeho kopírování. Generovaná hesla se maskují před zkrácením logů; původní chyba se zachová také při chybě úklidu.

Nové `TURTO-CRM-Kontrola-Pripojeni.exe` pouze ověřuje TCP spojení k databázovému a souborovému portu. Sestavené okno se zkouší proti skutečně otevřenému a zavřenému místnímu portu, ověřuje kopírování výsledku a odmítnutí cesty ke sdílené složce v poli server. Úspěšné testy kontrolního programu nedokládají dostupnost firemní VPN. Výsledek konkrétního sestavení je uveden v jeho workflow a přiložených JSON protokolech.

## Místní ukázka 0.3.0

Samostatný `TURTO-CRM-Mistni-Ukazka.exe` umožňuje zkoušku Společností bez přípravy firemního serveru. Každé spuštění vytvoří nový dočasný PostgreSQL pouze na 127.0.0.1, nahraje umělá data a připraví dvě přihlášení editora a jedno čtenáře. Běžné ukončení odstraní tuto zkušební databázi. Windows Job Object ukončí pomocné procesy i při násilném ukončení aplikace; po přerušení může zůstat neaktivní dočasná složka.

Windows workflow balí přiloženou distribuci PostgreSQL včetně licencí. Před vytvořením distribučního ZIP musí uspět skutečný EXE se založením a úpravou společnosti, dvěma okny a odmítnutím zastaralého zápisu, historií, přepnutím na čtenáře a odmítnutím zápisu přímo serverem. Test také ověřuje běžné i násilné ukončení databázového procesu, odstranění dočasných dat po běžném ukončení, zachování nastavení firemního připojení a nezávislost na PostgreSQL/Pythonu v PATH. Sestavení nesplňující tyto podmínky distribuční balíček nevytvoří. Výsledek konkrétního sestavení dokládá jeho běh workflow a soubor `local-demo.json` v artefaktu `network-windows-validation`.

Tato lokální zkouška neověřuje přístup přes firemní Wi-Fi ani VPN. Síťový klient nadále vyžaduje připravenou firemní databázi a při výpadku sítě na ukázku automaticky nepřechází. Návod k oběma způsobům spuštění je v [TRY-PILOT.md](TRY-PILOT.md).

## Dosavadní etapy převodu a firemního připojení

Datum kontroly 18. září 2026. Základ CRM 8.0.34, hlavní větev `d060d96`. Testovací větev `feature/postgresql-pilot` je dostupná jako [draft PR 108](https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/pull/108). Nebyla začleněna do hlavní větve ani vydána jako aktualizace.

**Převod dat i první serverová agenda Společnosti prošly na standardním PostgreSQL 16 a 18.** Výsledek potvrzuje [běh serverových a GUI testů](https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/actions/runs/35356801236) pro commit `c4de369d7859dcbd86ed0724ebcfd88b7c0ace1d`. Následující změna tohoto protokolu upravuje pouze dokumentaci.

## Provedené kontroly

Na každé verzi serveru prošlo 33 testů síťového pilotu: 21 kontrol převodu, 11 scénářů serverové agendy a 1 zkouška skutečného Tk okna. GUI scénář je v prvním běhu bez obrazovky výslovně přeskočený a následně se spouští samostatně přes Xvfb; celkový výsledek zahrnuje jeho úspěšné provedení.

| Oblast | Výsledek na PostgreSQL 16 i 18 |
| --- | --- |
| SQLite zdroj, profily, převod, souběh migrací a obnova | 21 testů prošlo |
| Osobní účty, serverová práva, souběžné editace, historie a obnova upraveného pilotu | 11 testů prošlo |
| Skutečné Tk okno: přihlášení, editace, konflikt, čtenář a zavírání | 1 test prošel |
| Stávající správa souborů a záloh CRM | Dalších 14 regresních testů prošlo |
| Stávající oprávnění CRM 8.0.34 | Databázová regresní kontrola prošla |
| Úplné schéma aktuálního CRM použité k převodu | 50 běžných tabulek, 38 původních triggerů a 89 explicitních indexů v inventuře |
| Práce na dvou skutečných PC přes firemní síť | Síťový pilot zatím takto neověřen |

## Co serverové scénáře prokázaly

Převod ověřil všechny běžné tabulky schématu CRM se zkušebními obchodními záznamy, české texty, binární přílohy, duplicity, číselné hodnoty, zachování ID a čítačů po odstraněných řádcích. Kontroly zahrnují porovnání počtů i SHA-256 obsahu, cizí a unikátní klíče, odmítnutí přepsání existujícího cíle, rollback celého převodu, dva souběžné převody a skrytí hesla při chybě spojení.

Serverové Společnosti ověřily skutečné osobní LOGIN role a odmítnutí nesprávného hesla. Čtenář nemůže ukládat, skrytá agenda nevrací data, neaktivní osoba a chybné nastavení práv jsou odmítnuté. Přímý přístup k obchodním tabulkám a historii, volání interní autorizační funkce a podvržení uživatele klientským nastavením jsou zakázané. Odebrání přístupu funguje i v již otevřeném spojení; snížení práv platí pro následující zápis.

Dvě různé osoby otevřely stejnou verzi společnosti a zkusily ji současně uložit. Uložila se přesně jedna změna; druhá skončila konfliktem a historie obsahovala skutečný účet úspěšné osoby. Duplicitní doručení stejného požadavku založilo pouze jednu firmu. Ztracená odpověď po dokončeném zápisu byla ověřena podle ID požadavku bez opakování změny. Vyvolaná chyba zápisu historie vrátila zpět firmu i evidenci požadavku.

Záloha přes `pg_dump` byla skutečně obnovena přes `pg_restore` do jiné databáze. Původní převod prošel opětovným porovnáním všech tabulek. Další scénář obnovil již upravenou společnost, její historii a omezený přístup osobního účtu; standardní záloha upravené kopie vyžaduje výslovný parametr `--allow-pilot-changes`.

GUI test stiskl skutečná tlačítka přihlášení a ukládání, ověřil vymazání hesla z formuláře, zobrazení konfliktu a zakázaná tlačítka čtenáře. Také ověřil, že volání klávesové obsluhy bez události při zániku Tk prvků nespustí ukládání. Snímky testovacího okna jsou uložené v artefaktech uvedeného běhu.

## Rozsah hotové etapy

Společnosti mají samostatné serverové okno dostupné v Nastavení testovací aplikace. Příprava serveru a účtů je popsaná v [DIRECTORY.md](DIRECTORY.md). Manifest obsahuje `directory_api_version=1` a nadále `application_ready=false`.

Další agendy, společné přepnutí celého CRM, úplné serverové schéma a triggery, Přehledy, externí přílohy, distribuční přepnutí celého CRM a automatické zálohování na firemní infrastruktuře zůstávají dalšími kroky. Místní a serverová data se automaticky nesynchronizují. Vaše provozní databáze nebyla na server převáděna; testy použily izolovaný základ ze zdrojů CRM a zkušební záznamy.

## Samostatný Windows pilot 0.2.0

Navazující změna doplňuje připojení k firemnímu serveru v kanceláři i přes VPN, formulář nastavení, uchování profilu bez hesla, ukázkovou databázi a dvojici přenositelných EXE. [Aktuální běhy workflow](https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/actions/workflows/validate-postgresql-pilot.yml) obsahují výsledky sestavení a archiv ke stažení. Původní odkazy výše dokládají předchozí serverovou etapu; konkrétní Windows sestavení potvrzuje jeho vlastní úspěšný běh.

Workflow nově provádí šest kontrol nastavení a výpadků spojení, dosavadní scénáře PostgreSQL 16/18 a kontrolu přímo ve Windows proti samostatnému PostgreSQL 17 s TLS certifikátem. Sestavený nástroj správce připraví umělou databázi a přiřadí omezené účty. Následně hotové GUI EXE projde formulář připojení, přihlášení editora, založení a úpravu firmy, historii a samostatné přihlášení čtenáře. Program se při této kontrole spouští z prázdné pracovní složky a bez PostgreSQL v PATH. Archiv vznikne pouze po úspěšném výsledku obou EXE relací; obsahuje identifikaci sestaveného commitu a samostatný SHA-256 soubor.

Firemní server, skutečná kancelářská Wi-Fi, firemní VPN a konkrétní počítače uživatele tímto ještě nejsou ověřené. Postup pro tuto zkoušku je v [TRY-PILOT.md](TRY-PILOT.md), požadavky správce v [SERVER.md](SERVER.md).
